"""
RPGMaker Workflow Tab - Automation hub for the full translation pipeline.

Provides a guided, step-by-step interface:

  Step 0  – Select game project folder and import data files into files/
  Step 1  – (Optional) Pre-process game files
  Step 2  – Setup: speaker flags, Project Setup skill, vocab / quirks / game skill
  Step 3  – Translation: Phase 0 (DB), Phase 1 (dialogue), Phase 1b (111 cache)
  Step 4  – Translation Phase 2 (risky codes)
  Step 5  – Plugins.js prompt helpers and export translated/ to the game
  Step 6  – Deterministically rewrap and QA the exported game data
  Step 7  – Prepare and translate editable bitmap UI images
  Step 8  – Install TL Inspector and/or Forge playtest plugins
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from util.paths import APP_NAME, ORG_NAME, ensure_game_glossary
from util.skills import load_clipboard_skill, load_project_setup
from util.vocab import BASE_SEPARATOR as _SHARED_BASE_SEPARATOR

import jsbeautifier
from dotenv import dotenv_values

from PyQt5.QtCore import Qt, QSettings, QSize, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QBoxLayout,
    QCheckBox,
    QComboBox,
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

from gui.setup_skills_editors import SetupSkillsEditors
from gui.theme import COLORS, Geometry, Spacing, application_stylesheet
from gui.workflow_components import (
    DisclosureSection,
    StatusBanner,
    WorkflowActivityPanel,
    WorkflowPageHeader,
    WorkflowStageCard,
    WorkflowStepRail,
    make_workflow_button,
)

from gui.translation_tab import (
    BATCH_MODE_LABEL,
    BATCH_MODE_BENEFIT_NOTE,
    BATCH_COLLECT_LIVE_CHARGE_NOTE,
    default_translation_mode,
)
from gui.ui_components import CheckableFileList, equalize_button_widths

WORKFLOW_TL_NORMAL_LABEL = "Normal Translate"

_STEP_PURPOSES = {
    0: "Detect the game and choose which data files enter this translation run.",
    1: "Optionally format project files and install the GameUpdate helper.",
    2: "Configure speaker detection, collect names, and maintain project guidance.",
    3: "Translate database and dialogue text, then build the variable cache.",
    4: "Translate audited variable, plugin, and script text only when required.",
    5: "Prepare plugin or script text and export reviewed translations to the game.",
    6: "Rewrap exported text and run the final game-data audit.",
    7: "Check image readiness, then continue in the Image Manager.",
    8: "Configure playtest tools, inspect the finished game, and build the public release.",
}

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
    # Comment continuations are project-dependent: plugins sometimes display
    # them, but most games use them only as internal editor notes.
    "CODE408": False,
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


class _RpgMakerRewrapWorker(QThread):
    """Scan or rewrite exported RPG Maker game JSON without invoking AI."""

    done = pyqtSignal(object, bool)  # RewrapReport, apply
    failed = pyqtSignal(str)

    def __init__(self, directory: str, options, file_names: list[str], *, apply: bool):
        super().__init__()
        self.directory = directory
        self.options = options
        self.file_names = list(file_names)
        self.apply = bool(apply)

    def run(self):
        try:
            from util.rpgmaker_rewrap import rewrap_directory

            report = rewrap_directory(
                self.directory,
                self.options,
                file_names=self.file_names,
                apply=self.apply,
            )
            self.done.emit(report, self.apply)
        except Exception as exc:  # noqa: BLE001 - surface worker errors in the UI
            self.failed.emit(str(exc))


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


# Never copy these into a game root when applying gameupdate/ (local updater state
# or stray translator assets that must not overwrite a live install).
_GAMEUPDATE_COPY_SKIP_NAMES = frozenset({
    "previous_patch_sha.txt",
})

# UberWolf is only useful for WOLF RPG Editor archives. The generic workflow
# handles RPG Maker MV/MZ/Ace and must never install these files; the dedicated
# WOLF workflow intentionally continues using the smaller shared skip set.
_WOLF_ONLY_GAMEUPDATE_NAMES = frozenset({
    "UberWolfCli.exe",
    "UberWolfCli.LICENSE.txt",
})
_RPG_GAMEUPDATE_COPY_SKIP_NAMES = (
    _GAMEUPDATE_COPY_SKIP_NAMES | _WOLF_ONLY_GAMEUPDATE_NAMES
)


class _FileCopyWorker(QThread):
    """Recursively copy a source folder into a destination folder."""
    done = pyqtSignal(int, list)   # count_copied, errors
    log  = pyqtSignal(str)

    def __init__(self, src: str, dst: str, skip_names: frozenset[str] | None = None):
        super().__init__()
        self.src = src
        self.dst = dst
        self.skip_names = skip_names or frozenset()

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
            if fp.name in self.skip_names:
                self.log.emit(f"  skipped {fp.relative_to(src)}")
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


class _ReleaseZipWorker(QThread):
    """Build a sanitized public-release ZIP without blocking the GUI."""

    done = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)

    def __init__(self, game_root: str, output_path: str):
        super().__init__()
        self.game_root = game_root
        self.output_path = output_path

    def run(self):
        try:
            from util.release_package import create_release_zip

            result = create_release_zip(
                self.game_root,
                self.output_path,
                progress=lambda current, total, label: self.progress.emit(
                    current, total, label
                ),
            )
            self.done.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


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


# Per-step help copy shown by the header ? button (keeps step UIs compact).
_STEP_HELP: dict[int, str] = {
    0: (
        "<b>Step 0 - Choose the game and its files</b><br><br>"
        "<b>What to do</b><br>"
        "1. Click <b>Choose game folder</b> and select the folder you normally open to play "
        "the game.<br>"
        "2. Check that the detected RPG Maker version and data folder look correct.<br>"
        "3. Choose the files you want to translate. The default selection is suitable for "
        "most games.<br>"
        "4. Click <b>Import selected files</b>.<br><br>"
        "Importing creates working copies for DazedTL. It does not change the game. When "
        "switching to a different game, clear the previous working files when prompted so "
        "the two projects do not get mixed together."
    ),
    1: (
        "<b>Step 1 - Prepare the project (optional)</b><br><br>"
        "Most beginners can leave the detected paths alone.<br><br>"
        "<b>What to do</b><br>"
        "• Use <b>Format game data</b> to make the game's data files easier to inspect.<br>"
        "• Use <b>Format plugins.js</b> to make the MV/MZ plugin list easier to read.<br>"
        "• Use <b>Install GameUpdate</b> only when you want that patch helper in the game.<br>"
        "• Or click <b>Run available tasks</b> to run every task that is ready.<br><br>"
        "Unavailable tasks are skipped. You can also skip this entire step and continue."
    ),
    2: (
        "<b>Step 2 - Set up speakers and game guidance</b><br><br>"
        "<b>What to do (in order)</b><br>"
        "1. Click <b>Collect names</b>. This finds likely speaker names and adds them to the "
        "Glossary; it does not translate dialogue.<br>"
        "2. Click <b>Copy setup instructions</b>, paste them into your AI helper, and let it "
        "inspect the game folder.<br>"
        "3. Turn on a speaker option only when the helper marks it <b>ENABLE</b>. Many games "
        "need no extra options.<br>"
        "4. If you enabled an option, click <b>Collect names</b> again.<br>"
        "5. Put each labeled result into its matching tab: <b>Glossary</b>, "
        "<b>Translation quirks</b>, or <b>Game skill</b>, then save it.<br><br>"
        "Keep the Glossary short and useful. Character names, places, and recurring terms "
        "belong there; long general instructions do not."
    ),
    3: (
        "<b>Step 3 - Translate the main game text</b><br><br>"
        "<b>What to do</b><br>"
        "1. Leave <b>Normal Translate</b> selected unless you already know you want Batch "
        "Translate.<br>"
        "2. Enter the line widths recommended by the setup helper and click "
        "<b>Save line widths</b>.<br>"
        "3. Click <b>Translate database</b> for item names, descriptions, and other menu "
        "text.<br>"
        "4. Click <b>Translate dialogue</b> for conversations and choices.<br>"
        "5. Click <b>Build variable cache</b> before continuing to Phase 2.<br><br>"
        "Leave <b>Include displayed comment text</b> off unless the setup helper specifically "
        "says this game displays that text. Each translation button opens the Translation "
        "page and starts the matching work."
    ),
    4: (
        "<b>Step 4 - Translate unusual text sources</b><br><br>"
        "This step is optional. Most games do not need every choice shown here.<br><br>"
        "<b>What to do</b><br>"
        "1. Click <b>Copy advanced-text audit</b> and paste it into your AI helper with the "
        "game folder open.<br>"
        "2. Enable only the text sources the helper confirms are visible to players.<br>"
        "3. If it recommends plugin or script text, open <b>Advanced plugin and script "
        "filters</b> and select only the confirmed entries.<br>"
        "4. Click <b>Translate selected text</b>.<br><br>"
        "If the audit does not identify extra player-visible text, leave everything off and "
        "continue. Guessing here can change text the game uses internally."
    ),
    5: (
        "<b>Step 5 - Put translated text into the game</b><br><br>"
        "<b>What to do</b><br>There are two different jobs on this page:<br><br>"
        "<b>Plugin or script text</b><br>"
        "1. The selected game's <b>glossary.txt</b> is already available in its root folder.<br>"
        "2. Copy the plugin or Ruby translation skill and paste it into your AI helper.<br>"
        "3. Review the proposed changes. The helper edits approved plugin or script files "
        "directly inside the game folder, so these changes do not need the Export buttons.<br><br>"
        "<b>Main translated game data</b><br>"
        "• <b>Export selected files</b> writes only the files chosen in Step 0 into the game.<br>"
        "• <b>Export all translated files</b> writes every completed translation into the "
        "game.<br><br>"
        "Use <b>Export selected files</b> unless you intentionally translated additional files. "
        "Exporting is the first point where DazedTL replaces game data, so keep a backup or "
        "use Git before continuing."
    ),
    6: (
        "<b>Step 6 - Fix line wrapping and run final text checks</b><br><br>"
        "Complete Export in Step 5 before using this page.<br><br>"
        "<b>What to do</b><br>"
        "1. Choose which game-data files and kinds of text to check. The presets are enough "
        "for most games.<br>"
        "2. Confirm the saved line widths. Open the advanced choices only when you need a "
        "special limit.<br>"
        "3. Click <b>Preview rewrap</b>. This shows proposed line-break changes without saving "
        "them.<br>"
        "4. Review the results, then click <b>Apply rewrap</b>.<br>"
        "5. Click <b>Copy final QA skill</b>, paste it into your AI helper, and fix the problems "
        "it reports.<br><br>"
        "Continue through Images and Playtest before building the public release."
    ),
    7: (
        "<b>Step 7 - Translate text inside images</b><br><br>"
        "This guided image step is available for MV/MZ games.<br><br>"
        "<b>What to do</b><br>"
        "1. Click <b>Refresh readiness</b> and resolve any warning it shows.<br>"
        "2. Click <b>Open Image Manager</b>.<br>"
        "3. Make the images you want to translate editable.<br>"
        "4. Click <b>Copy skill</b> in Image Manager and paste it into your AI helper.<br>"
        "5. Review every edited image, then use <b>Patch selected</b> or <b>Patch all</b> to "
        "put approved images back into the game.<br><br>"
        "The image skill uses the Glossary already copied to the game in Step 5. It edits "
        "working PNG copies first, not the game's original image files."
    ),
    8: (
        "<b>Step 8 - Playtest and build the release</b><br><br>"
        "This page is available for MV/MZ games.<br><br>"
        "<b>What to do</b><br>"
        "1. Choose the hotkeys and screen size for the playtest tools, then click "
        "<b>Save defaults</b>.<br>"
        "2. Install <b>TL Inspector</b>, <b>Forge</b>, or both.<br>"
        "3. Launch the game and verify that the tools open with the chosen hotkeys.<br>"
        "4. Play through the translated game. Check dialogue, menus, choices, images, and "
        "important scenes.<br>"
        "5. Fix anything you find and repeat the relevant checks.<br>"
        "6. When the game is ready to share, click <b>Build public release ZIP</b>.<br><br>"
        "Building the ZIP is the final workflow action. It leaves the game folder unchanged "
        "and leaves translator workspaces, Git files, backups, and saves out of the ZIP."
    ),
}


def _show_step_help(parent: QWidget | None, title: str, html: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Information)
    box.setTextFormat(Qt.RichText)
    box.setText(html)
    box.setStandardButtons(QMessageBox.Ok)
    box.setStyleSheet(
        "QMessageBox{background-color:#252526;}"
        "QLabel{color:#c8c8c8;font-size:13px;min-width:420px;}"
    )
    box.exec_()


def _make_section_label(text: str) -> QLabel:
    """Compatibility section heading shared with the WOLF workflow."""

    label = QLabel(text)
    label.setObjectName("workflowSectionTitle")
    label.setStyleSheet(
        f"color:{COLORS.text_primary};font-size:14px;font-weight:600;"
        f"padding:6px 0 6px 10px;border-left:3px solid {COLORS.accent_text};"
        "background:transparent;"
    )
    return label


def _make_hr() -> QFrame:
    """Compatibility divider shared with the WOLF workflow."""

    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Plain)
    line.setStyleSheet(f"color:{COLORS.border};margin:8px 0 4px 0;")
    return line


def _make_btn(text: str, color: str = "#0e639c") -> QPushButton:
    """Create a semantic workflow button while preserving legacy call sites."""
    normalized = color.lower().strip()
    if normalized in {"#7a3a3a", "#8b0000", "#cc2222", "#cc4444", "#a1260d"}:
        variant = "danger"
    elif normalized in {
        "#45454a", "#555", "#5a5a60", "#444", "#444444",
        "#8a6d3b",
        COLORS.border.lower(), COLORS.border_strong.lower(), COLORS.surface_1.lower(),
    }:
        variant = "secondary"
    else:
        variant = "primary"
    btn = make_workflow_button(text, variant=variant)
    try:
        _icon_color = {
            "primary": "#ffffff",
            "danger": COLORS.danger,
            "secondary": COLORS.text_secondary,
        }[variant]
    except KeyError:
        _icon_color = COLORS.text_secondary
    from gui import qt_icons

    qt_icons.apply_button_icon(btn, text, color=_icon_color)
    if not btn.icon().isNull():
        btn.setIconSize(QSize(16, 16))
    return btn


def _make_text_btn(label: str, tooltip: str = "", *, min_width: int = 52) -> QPushButton:
    """Compact labeled button for file-list actions (All / None / Core / Import)."""
    btn = make_workflow_button(label, variant="secondary", tooltip=tooltip)
    btn.setFont(QFont("Segoe UI", 10))
    btn.setMinimumWidth(min_width)
    btn.setMinimumHeight(Geometry.CONTROL)
    return btn


def _make_icon_btn(icon_text: str, tooltip: str = "") -> QPushButton:
    """Compact icon-only button (e.g. folder browse)."""
    from gui import qt_icons

    btn = make_workflow_button("", variant="secondary", tooltip=tooltip)
    qt_icons.apply_button_icon(btn, icon_text, color="#f2f2f2")
    btn.setIconSize(QSize(18, 18))
    btn.setFont(QFont("Segoe UI", 12))
    btn.setFixedWidth(40)
    btn.setMinimumHeight(Geometry.CONTROL)
    return btn


def _size_action_button(
    button: QPushButton,
    width: int = Geometry.ACTION,
    *,
    expanding: bool = False,
    maximum: int | None = None,
) -> QPushButton:
    """Apply a shared action tier instead of page-specific button geometry."""
    button.setMinimumWidth(width)
    button.setMaximumWidth(
        maximum
        if maximum is not None
        else Geometry.ACTION_MAX
        if width >= Geometry.ACTION
        else Geometry.ACTION
    )
    button.setMinimumHeight(Geometry.CONTROL)
    button.setSizePolicy(
        QSizePolicy.Expanding if expanding else QSizePolicy.Preferred,
        QSizePolicy.Fixed,
    )
    return button


def _equalize_action_buttons(
    *buttons: QPushButton,
    width: int = Geometry.ACTION,
    maximum: int | None = None,
) -> None:
    """Give related actions the same footprint and baseline."""
    for button in buttons:
        button.setMinimumHeight(Geometry.CONTROL)
    equalize_button_widths(
        buttons,
        minimum=width,
        maximum=maximum if maximum is not None else Geometry.ACTION_MAX,
    )


def _make_form_label(text: str, width: int = Geometry.FORM_LABEL) -> QLabel:
    """Create a stable label column shared by workflow form rows."""
    label = QLabel(text)
    label.setObjectName("workflowFormLabel")
    label.setMinimumWidth(width)
    label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return label


def _inspect_image_workflow(game_root: str | Path) -> dict:
    """Return lightweight MV/MZ image-workflow readiness details."""
    root = Path(game_root).expanduser().resolve()
    report = {
        "root": root,
        "ok": False,
        "error": "",
        "runtime": 0,
        "encrypted": 0,
        "editable": 0,
        "misplaced": 0,
        "vocab": root / "glossary.txt",
        "editable_root": None,
        "key_ok": None,
    }
    try:
        from util.rpgmaker_images import (
            editable_workspace_root,
            read_encryption_key,
            resolve_content_root,
            scan_image_assets,
        )

        content_root = resolve_content_root(root)
        workspace = editable_workspace_root(root)
        expected_root = workspace / content_root.relative_to(root) / "img"
        assets = scan_image_assets(root)
        encrypted = sum(asset.has_encrypted for asset in assets)
        report.update(
            {
                "ok": True,
                "runtime": sum(
                    asset.has_encrypted or asset.has_runtime_plain for asset in assets
                ),
                "encrypted": encrypted,
                "editable": sum(asset.has_plain for asset in assets),
                "editable_root": expected_root,
            }
        )
        if encrypted:
            try:
                read_encryption_key(root)
                report["key_ok"] = True
            except Exception:
                report["key_ok"] = False

        if workspace.is_dir():
            misplaced = 0
            for path in workspace.rglob("*"):
                if not path.is_file() or path.suffix.casefold() != ".png":
                    continue
                try:
                    path.relative_to(expected_root)
                except ValueError:
                    misplaced += 1
            report["misplaced"] = misplaced
    except Exception as exc:
        report["error"] = str(exc)
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Main widget
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowTab(QWidget):
    """Guided automation tab for the full RPGMaker translation workflow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        try:
            self.settings = QSettings(ORG_NAME, APP_NAME)
        except Exception:
            self.settings = None

        # State
        self._data_path: str | None = None
        self._engine: str = "MVMZ"
        self._file_items: list[dict] = []
        self._worker = None  # active background QThread
        self._rewrap_worker = None
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
        self._release_zip_btn: QPushButton | None = None
        self._tl_mode_user_selected = False
        self._last_default_translation_mode = None
        self._activity_unread = 0
        self._activity_errors = 0

        self._init_ui()

    # ───────────────────────────────── UI setup ──────────────────────────────

    def _init_ui(self):
        self.setObjectName("workflowRoot")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Main content and the optional Activity panel share a splitter so the
        # user can adjust the detail area without changing page geometry.
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("workflowSplitter")
        splitter.setHandleWidth(1)
        self._workflow_splitter = splitter

        self._step_tabs = QTabWidget()
        self._step_tabs.setObjectName("workflowStepStack")
        self._step_tabs.setDocumentMode(True)
        self._step_tabs.tabBar().setVisible(False)
        self._step_tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background-color: #1e1e1e; top: 0; }
            QTabBar { height: 0; max-height: 0; }
        """)

        _tab_defs = [
            ("0  Project",      self._build_step0),
            ("1  Pre-process",  self._build_step1_preprocess),
            ("2  Setup",        self._build_step2_setup),
            ("3  TL Phase 1",   self._build_step4_translation),
            ("4  TL Phase 2",   self._build_step5_tl_phase2),
            ("5  Export",       self._build_step5_finish),
            ("6  Rewrap",       self._build_step5_rewrap),
            ("7  Images",       self._build_step6_images),
            ("8  Playtest",     self._build_step8_playtest),
        ]
        self._step_labels = [label for label, _ in _tab_defs]
        rail_labels = [
            "Project", "Prepare", "Setup", "Phase 1", "Phase 2",
            "Export", "Rewrap", "Images", "Playtest",
        ]
        self._step_done: set[int] = set()
        self._step_rail = WorkflowStepRail(rail_labels)
        self._step_strip = self._step_rail  # compatibility for older integrations
        self._step_buttons = self._step_rail.buttons
        self._step_rail.step_requested.connect(self._goto_step)

        for tab_label, builder in _tab_defs:
            # Each tab: outer page → scroll area → inner content widget
            page = QWidget()
            page.setObjectName("workflowPage")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(0)

            scroll = QScrollArea()
            scroll.setObjectName("workflowPageScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)

            inner = QWidget()
            inner.setObjectName("workflowPageContent")
            vbox = QVBoxLayout(inner)
            vbox.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.MD)
            vbox.setSpacing(Spacing.MD)

            builder(vbox)
            vbox.addStretch()

            scroll.setWidget(inner)
            page_layout.addWidget(scroll, 1)

            # ── Navigation footer ──────────────────────────────────────────
            nav = QWidget()
            nav.setObjectName("workflowFooter")
            nav.setStyleSheet(
                f"QWidget#workflowFooter{{background:{COLORS.chrome};"
                f"border-top:1px solid {COLORS.border};}}"
            )
            nav_layout = QHBoxLayout(nav)
            nav_layout.setContentsMargins(Spacing.LG, Spacing.SM, Spacing.LG, Spacing.SM)
            nav_layout.setSpacing(Spacing.SM)

            tab_idx = len(self._step_tabs)  # current tab index (before addTab)

            if tab_idx > 0:
                back_btn = make_workflow_button("←  Back", variant="secondary")
                back_btn.setMinimumWidth(120)
                _idx = tab_idx  # capture for lambda
                back_btn.clicked.connect(
                    lambda _checked, i=_idx: self._goto_step(i - 1)
                )
                nav_layout.addWidget(back_btn)

            nav_layout.addStretch()

            if tab_idx < len(_tab_defs) - 1:
                next_btn = make_workflow_button("Continue  →", variant="primary")
                next_btn.setMinimumWidth(120)
                _idx = tab_idx  # capture for lambda
                next_btn.clicked.connect(
                    lambda _checked, i=_idx: self._advance_step(i)
                )
                nav_layout.addWidget(next_btn)

            page_layout.addWidget(nav)
            self._step_tabs.addTab(page, tab_label)

        self._step_tabs.currentChanged.connect(self._on_step_tab_changed)
        self._step_rail.set_current(0)

        steps_host = QWidget()
        steps_host.setObjectName("workflowStepsHost")
        steps_host_layout = QHBoxLayout(steps_host)
        steps_host_layout.setContentsMargins(0, 0, 0, 0)
        steps_host_layout.setSpacing(0)
        steps_host_layout.addWidget(self._step_strip)
        steps_host_layout.addWidget(self._step_tabs, 1)
        splitter.addWidget(steps_host)

        # ---- Right: collapsible Activity panel ----
        self._activity_panel = WorkflowActivityPanel()
        self.log_area = self._activity_panel.log
        self._activity_panel.clear_requested.connect(self._clear_activity)
        self._activity_panel.collapse_requested.connect(
            lambda: self._set_activity_visible(False)
        )
        self._step_rail.activity_requested.connect(self._toggle_activity)
        splitter.addWidget(self._activity_panel)
        splitter.setSizes([980, Geometry.ACTIVITY_WIDTH])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        root.addWidget(splitter)
        self._apply_theme()
        saved_activity = str(self._setting("activity_panel_visible", "false")).lower()
        self._set_activity_visible(saved_activity in {"1", "true", "yes", "on"}, persist=False)
        self._detected_on_show: bool = False  # guard: only auto-detect once per new folder

    # ── Tab visibility ──────────────────────────────────────────────────────

    def showEvent(self, event):
        """Refresh live settings and detect the saved folder when first shown."""
        super().showEvent(event)
        self._update_responsive_shell()
        self.refresh_wrap_widths_from_env()
        if not self._detected_on_show and self._setting("last_game_folder", ""):
            self._detected_on_show = True
            QTimer.singleShot(100, self._detect_folder)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_shell()

    def _update_responsive_shell(self):
        rail = getattr(self, "_step_rail", None)
        if rail is not None:
            rail.set_compact(
                self.width() < 1320 or rail.labels_require_compact_mode()
            )
            self._refresh_activity_badge()
        rewrap_layout = getattr(self, "_rewrap_workspace_layout", None)
        if rewrap_layout is not None:
            rewrap_layout.setDirection(
                QBoxLayout.TopToBottom
                if self.width() < 1500
                else QBoxLayout.LeftToRight
            )
        setup_layout = getattr(self, "_setup_workspace_layout", None)
        if setup_layout is not None:
            setup_layout.setDirection(
                QBoxLayout.TopToBottom
                if self.width() < 1500
                else QBoxLayout.LeftToRight
            )

    def _set_activity_visible(self, visible: bool, *, persist: bool = True):
        panel = getattr(self, "_activity_panel", None)
        if panel is None:
            return
        panel.setVisible(bool(visible))
        if visible:
            self._activity_unread = 0
            self._activity_errors = 0
        rail = getattr(self, "_step_rail", None)
        if rail is not None:
            rail.activity_button.setCheckable(True)
            rail.activity_button.setChecked(bool(visible))
            self._refresh_activity_badge()
        if visible and hasattr(self, "_workflow_splitter"):
            available = max(1, self._workflow_splitter.width())
            activity_width = min(Geometry.ACTIVITY_WIDTH, max(240, available // 3))
            self._workflow_splitter.setSizes([available - activity_width, activity_width])
        if persist:
            self._save_setting("activity_panel_visible", "true" if visible else "false")

    def _toggle_activity(self):
        panel = getattr(self, "_activity_panel", None)
        if panel is not None:
            self._set_activity_visible(not panel.isVisible())

    def _clear_activity(self):
        self._activity_panel.clear_activity()
        self._activity_unread = 0
        self._activity_errors = 0
        self._refresh_activity_badge()

    def _refresh_activity_badge(self):
        rail = getattr(self, "_step_rail", None)
        panel = getattr(self, "_activity_panel", None)
        if rail is None or panel is None:
            return
        if panel.isVisible():
            text = "×" if rail._compact else "Hide"
        else:
            text = (
                (str(min(self._activity_unread, 99)) if self._activity_unread else "⋯")
                if rail._compact else "Activity"
            )
            if self._activity_unread and not rail._compact:
                text += f" {self._activity_unread}"
        rail.activity_button.setText(text)
        if self._activity_errors:
            rail.activity_button.setToolTip(
                f"{self._activity_errors} error message(s) in workflow activity"
            )
            rail.activity_button.setStyleSheet(f"color:{COLORS.danger};")
        else:
            rail.activity_button.setToolTip(
                "Show or hide workflow activity and detailed log"
            )
            rail.activity_button.setStyleSheet("")

    def _step_strip_label(self, idx: int, *, done: bool) -> str:
        """Compact strip text: number + short name, optional checkmark for done."""
        short_names = (
            "Project",
            "Prep",
            "Setup",
            "Phase1",
            "Phase2",
            "Export",
            "Rewrap",
            "Images",
            "Playtest",
        )
        name = short_names[idx] if 0 <= idx < len(short_names) else str(idx)
        mark = "✓" if done else ""
        return f"{mark}{idx + 1}\n{name}"

    def _refresh_step_strip(self, current: int | None = None):
        if current is None:
            current = self._step_tabs.currentIndex() if hasattr(self, "_step_tabs") else 0
        rail = getattr(self, "_step_rail", None)
        if rail is not None:
            rail.set_done(self._step_done)
            rail.set_current(current)
            return
        for i, btn in enumerate(getattr(self, "_step_buttons", [])):
            if not btn.isVisible():
                continue
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
        # Skip hidden steps (e.g. Playtest on Ace).
        buttons = getattr(self, "_step_buttons", [])
        if 0 <= idx < len(buttons) and not buttons[idx].isVisible():
            # Prefer previous visible step.
            for j in range(idx - 1, -1, -1):
                if buttons[j].isVisible():
                    idx = j
                    break
        if self._step_tabs.currentIndex() != idx:
            self._step_tabs.setCurrentIndex(idx)
        else:
            self._refresh_step_strip(idx)

    def _advance_step(self, from_idx: int):
        """Mark *from_idx* done and move to the next visible step."""
        self._step_done.add(from_idx)
        nxt = from_idx + 1
        buttons = getattr(self, "_step_buttons", [])
        while nxt < len(buttons) and not buttons[nxt].isVisible():
            nxt += 1
        self._goto_step(nxt)

    def _on_step_tab_changed(self, index: int):
        """Refresh config-backed controls when their workflow page is shown."""
        previous_index = self._current_step_index
        self._current_step_index = index
        self._refresh_step_strip(index)

        if previous_index == 0 and index != 0:
            self._auto_import_if_needed()

        if index == 3:
            self.refresh_wrap_widths_from_env()
        if index == 4:
            self._populate_p2_checkboxes()
        if index == 6:
            self._refresh_rewrap_files()
        if index == 7:
            self._refresh_image_workflow_status()
        if index == 8:
            self._refresh_playtest_status()
            self._load_playtest_settings()

    def _register_import_button(self, button: QPushButton) -> None:
        self._import_buttons.append(button)

    def _set_import_buttons_enabled(self, enabled: bool) -> None:
        for button in self._import_buttons:
            button.setEnabled(enabled)

    def _apply_theme(self):
        """Make standalone workflow widgets honor the canonical application theme."""
        self.setStyleSheet(application_stylesheet())

    # ── Step 0: Project Folder ──────────────────────────────────────────────

    def _add_step_header(
        self,
        layout: QVBoxLayout,
        title: str,
        step_idx: int,
        *,
        extra_widgets: list | None = None,
    ) -> QLabel:
        """Add the standard workflow eyebrow, title, purpose, and Help action."""
        display_title = title.split("—", 1)[-1].strip()
        display_title = display_title.replace("(Optional)", "").strip()
        header = WorkflowPageHeader(
            step_idx,
            display_title,
            _STEP_PURPOSES.get(step_idx, "Complete this workflow step."),
            optional=step_idx == 1,
        )
        for widget in extra_widgets or []:
            # The standard header already owns the Optional badge. Preserve
            # functional trailing controls such as the Prepare disclosure.
            if isinstance(widget, QLabel) and widget.text().strip().lower() == "optional":
                widget.hide()
                continue
            header.add_trailing_widget(widget)
        help_html = _STEP_HELP.get(step_idx, "No help is available for this step.")
        header.help_requested.connect(
            lambda label=header.title_label, h=help_html: _show_step_help(
                self, label.text(), h
            )
        )
        layout.addWidget(header)
        return header.title_label

    def _build_step0(self, layout: QVBoxLayout):
        self._add_step_header(layout, "Step 0 — Project & Files", 0)

        project_stage = WorkflowStageCard(
            1,
            "Select the RPG Maker project",
            "Choose the game folder. Detection identifies MV, MZ, or Ace and locates its data.",
        )
        row0 = QHBoxLayout()
        row0.setSpacing(Spacing.SM)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Game folder path…")
        saved = self._setting("last_game_folder", "")
        if saved:
            self.folder_edit.setText(saved)
        row0.addWidget(self.folder_edit, 1)
        self.folder_edit.returnPressed.connect(self._detect_folder)

        browse_btn = _make_icon_btn("📁", "Choose an RPG Maker game folder")
        browse_btn.clicked.connect(self._browse_folder)
        row0.addWidget(browse_btn)
        project_stage.add_layout(row0)

        self.detected_label = QLabel("No project selected.")
        self.detected_label.setStyleSheet(
            "color:#73c991;font-size:13px;padding:4px 8px;"
            "background-color:#1f2b1f;border:1px solid #2a4a2a;"
            "border-radius:4px;margin:4px 0;"
        )
        self.detected_label.setWordWrap(True)
        project_stage.add_widget(self.detected_label)
        layout.addWidget(project_stage)

        files_stage = WorkflowStageCard(
            2,
            "Select files to translate",
            "Start with the core database, then add the maps and events needed for this run.",
        )
        selection_row = QHBoxLayout()
        selection_row.setSpacing(Spacing.SM)
        select_all_btn = _make_text_btn("Select all", "Select every importable file", min_width=128)
        select_all_btn.clicked.connect(self._select_all_files)
        selection_row.addWidget(select_all_btn)

        deselect_all_btn = _make_text_btn("Clear selection", "Deselect every file", min_width=128)
        deselect_all_btn.clicked.connect(self._deselect_all_files)
        selection_row.addWidget(deselect_all_btn)

        sel_core = _make_text_btn(
            "Database only",
            "Select core database files and deselect maps and events",
            min_width=128,
        )
        sel_core.clicked.connect(self._select_core_only)
        selection_row.addWidget(sel_core)
        _equalize_action_buttons(
            select_all_btn,
            deselect_all_btn,
            sel_core,
            width=160,
            maximum=200,
        )
        for column in range(3):
            selection_row.setStretch(column, 1)
        selection_row.addStretch()
        files_stage.add_layout(selection_row)

        self.file_list = CheckableFileList()
        self.file_list.setMinimumHeight(320)
        self.file_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.file_list.setStyleSheet(
            "QListWidget{outline:none;border:1px solid #45454a;"
            "background-color:#252526;border-radius:4px;}"
            "QListWidget::item{border:none;outline:none;padding:2px 6px;"
            "color:#c8c8c8;}"
            f"QListWidget::item:selected{{background-color:{COLORS.selection};color:#ffffff;}}"
            "QListWidget::item:hover{background-color:#2d2d30;"
            "border-left:2px solid #0e639c;}"
        )
        files_stage.add_widget(self.file_list, 1)
        layout.addWidget(files_stage, 1)

        import_stage = WorkflowStageCard(
            3,
            "Import selected files",
            "Replace files/ with this selection. Existing translated output is not changed.",
        )
        import_row = QHBoxLayout()
        import_row.setSpacing(Spacing.SM)
        import_btn = _make_btn("↓  Import selected files", "#0e639c")
        _size_action_button(import_btn, Geometry.ACTION_WIDE)
        import_btn.setEnabled(False)
        import_btn.setToolTip("Replace files/ with exactly the selected files above")
        import_btn.clicked.connect(lambda _checked=False: self._import_files())
        self._register_import_button(import_btn)
        import_row.addWidget(import_btn)
        import_row.addStretch()
        import_stage.add_layout(import_row)
        layout.addWidget(import_stage)

    # ── Step 3: Vocab / Glossary ────────────────────────────────────────────

    # Static clipboard prompts are loaded from editable data/skills/*.md files.

    # ── Step 1 (Optional): Pre-process ────────────────────────────────

    def _build_step1_preprocess(self, layout: QVBoxLayout):
        opt_badge = QLabel("optional")
        opt_badge.setStyleSheet(
            "color:#77777a;font-size:11px;border:1px solid #45454a;"
            "padding:1px 8px;border-radius:8px;"
            "background-color:#252526;"
        )
        # Collapse/expand toggle
        toggle_btn = make_workflow_button("Hide optional", variant="quiet")
        toggle_btn.setCheckable(True)
        toggle_btn.setChecked(True)
        toggle_btn.setFixedSize(208, Geometry.CONTROL)
        toggle_btn.setToolTip("Show or hide the optional preparation tasks")
        self._add_step_header(
            layout,
            "Step 1 (Optional) — Prepare Project",
            1,
            extra_widgets=[opt_badge, toggle_btn],
        )

        # Collapsible container — wraps tasks_box + run-all row
        collapse_widget = QWidget()
        collapse_layout = QVBoxLayout(collapse_widget)
        collapse_layout.setContentsMargins(0, 0, 0, 0)
        collapse_layout.setSpacing(Spacing.XS)

        tasks_box = QGroupBox()
        tasks_box.setStyleSheet("QGroupBox{border:none;margin:0;padding:4px 0;}")
        tb = QVBoxLayout(tasks_box)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(Spacing.MD)
        collapse_layout.addWidget(tasks_box)

        # ---- Task A: dazedformat -----------------------------------------
        ta = WorkflowStageCard(
            1,
            "Format game data",
            "Normalize every JSON file with the bundled formatter before review or translation.",
        )
        ta_inner = ta.body
        self._pp_dazedformat_title = ta.title_label
        ta_path_row = QHBoxLayout()
        ta_path_row.addWidget(_make_form_label("Game data:"))
        self.pp_data_path_label = QLabel("(detect a project folder first)")
        self.pp_data_path_label.setStyleSheet("color:#77777a;font-size:13px;")
        ta_path_row.addWidget(self.pp_data_path_label, 1)
        ta_inner.addLayout(ta_path_row)
        ta_btn_row = QHBoxLayout()
        run_dazed = _make_btn("►  Format game data", "#555")
        run_dazed.setToolTip("Normalize the detected game-data JSON with dazedformat")
        run_dazed.clicked.connect(self._run_dazedformat)
        ta_btn_row.addWidget(run_dazed)
        ta_btn_row.addStretch()
        ta_inner.addLayout(ta_btn_row)
        tb.addWidget(ta)
        self._pp_dazedformat_box = ta

        # ---- Task B: prettier on plugins.js
        tb_box = WorkflowStageCard(
            2,
            "Format plugin configuration",
            "Make plugins.js easier to audit and edit without changing its behavior.",
        )
        tb_inner = tb_box.body
        self._pp_plugins_js_title = tb_box.title_label
        tb_path_row = QHBoxLayout()
        tb_path_lbl = _make_form_label("Plugin file:" )
        tb_path_row.addWidget(tb_path_lbl)
        self.pp_plugins_edit = QLineEdit()
        self.pp_plugins_edit.setPlaceholderText("plugins.js path…")
        tb_path_row.addWidget(self.pp_plugins_edit, 1)
        browse_plugins = _make_icon_btn("📁", "Choose the plugins.js file")
        browse_plugins.clicked.connect(self._browse_plugins_js)
        tb_path_row.addWidget(browse_plugins)
        tb_inner.addLayout(tb_path_row)
        tb_btn_row = QHBoxLayout()
        run_prettier = _make_btn("►  Format plugins.js", "#555")
        run_prettier.setToolTip("Format the selected plugins.js file for review")
        run_prettier.clicked.connect(self._run_prettier)
        tb_btn_row.addWidget(run_prettier)
        tb_btn_row.addStretch()
        tb_inner.addLayout(tb_btn_row)
        tb.addWidget(tb_box)
        self._pp_plugins_js_box = tb_box

        # ---- Task C: copy gameupdate/ -----------------------------------
        tc = WorkflowStageCard(
            3,
            "Install the GameUpdate helper",
            "Copy GameUpdate into the game and write its patch configuration from your saved defaults.",
        )
        tc_inner = tc.body

        tc_src_row = QHBoxLayout()
        tc_src_row.addWidget(_make_form_label("GameUpdate:"))
        self.pp_gameupdate_edit = QLineEdit()
        self.pp_gameupdate_edit.setPlaceholderText("GameUpdate source folder…")
        tc_src_row.addWidget(self.pp_gameupdate_edit, 1)
        browse_gu = _make_icon_btn("📁", "Choose the GameUpdate source folder")
        browse_gu.clicked.connect(self._browse_gameupdate)
        tc_src_row.addWidget(browse_gu)
        tc_inner.addLayout(tc_src_row)

        tc_dst_row = QHBoxLayout()
        tc_dst_row.addWidget(_make_form_label("Game folder:"))
        self.pp_gameupdate_dst_label = QLabel("(game root folder auto-filled from project)")
        self.pp_gameupdate_dst_label.setStyleSheet("color:#77777a;font-size:13px;")
        tc_dst_row.addWidget(self.pp_gameupdate_dst_label, 1)
        tc_inner.addLayout(tc_dst_row)

        tc_btn_row = QHBoxLayout()
        tc_btn_row.setSpacing(Spacing.SM)
        run_gu = _make_btn("►  Install GameUpdate", "#555")
        run_gu.setToolTip("Copy GameUpdate into the selected game folder")
        run_gu.clicked.connect(self._run_gameupdate)
        tc_btn_row.addWidget(run_gu)
        tc_btn_row.addStretch()
        tc_inner.addLayout(tc_btn_row)
        tb.addWidget(tc)

        # Keep the page-wide action separate from the final task. It applies to
        # every card above, so placing it in the GameUpdate card made it look
        # like part of that one task.
        self.pp_run_all_bar = QFrame()
        self.pp_run_all_bar.setObjectName("preprocessRunAllBar")
        self.pp_run_all_bar.setStyleSheet(
            f"QFrame#preprocessRunAllBar{{background:{COLORS.surface_1};"
            f"border:1px solid {COLORS.border};border-radius:6px;}}"
            f"QFrame#preprocessRunAllBar QLabel{{background:transparent;border:none;}}"
        )
        run_all_layout = QHBoxLayout(self.pp_run_all_bar)
        run_all_layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        run_all_layout.setSpacing(Spacing.MD)

        run_all_copy = QVBoxLayout()
        run_all_copy.setSpacing(Spacing.XS)
        run_all_title = QLabel("Run all preparation tasks")
        run_all_title.setStyleSheet(
            f"color:{COLORS.text_primary};font-size:13px;font-weight:600;"
        )
        run_all_copy.addWidget(run_all_title)
        run_all_hint = QLabel("Runs each task above when its required file or folder is available.")
        run_all_hint.setStyleSheet(f"color:{COLORS.text_muted};font-size:12px;")
        run_all_hint.setWordWrap(True)
        run_all_copy.addWidget(run_all_hint)
        run_all_layout.addLayout(run_all_copy, 1)

        run_all_btn = _make_btn("►►  Run available tasks", "#0e639c")
        run_all_btn.setToolTip("Run each preparation task whose required path is available")
        run_all_btn.clicked.connect(self._run_all_preprocess)
        equalize_button_widths(
            (
                run_dazed,
                run_prettier,
                run_gu,
                run_all_btn,
            ),
            minimum=Geometry.ACTION_WIDE,
            maximum=Geometry.ACTION_WIDE,
        )
        self.pp_preprocess_action_buttons = (
            run_dazed,
            run_prettier,
            run_gu,
            run_all_btn,
        )
        run_all_layout.addWidget(run_all_btn)
        collapse_layout.addWidget(self.pp_run_all_bar)

        layout.addWidget(collapse_widget)

        def _toggle_preprocess(expanded: bool):
            toggle_btn.setText("Hide optional" if expanded else "Show optional")
            collapse_widget.setVisible(expanded)
        toggle_btn.toggled.connect(_toggle_preprocess)

    @staticmethod
    def _task_box_style() -> str:
        return (
            "QWidget#tbox{"
            f"background-color:{COLORS.surface_1};"
            f"border:1px solid {COLORS.border};"
            "border-radius:6px;}"
        )

    @staticmethod
    def _checkbox_box_style() -> str:
        """Style for checkbox list container widgets."""
        return (
            "QWidget#cbbox{"
            f"background-color:{COLORS.surface_1};"
            f"border:1px solid {COLORS.border};"
            "border-radius:6px;}"
            "QWidget{"
            f"background-color:{COLORS.surface_1};"
            "border:none;}"
            "QCheckBox{border:none;background-color:transparent;}"
        )


    def _build_step2_setup(self, layout: QVBoxLayout):
        """Combined speaker flags + Project Setup + vocab/quirks/game-skill editors."""
        self._add_step_header(layout, "Step 2 — Speakers & Guidance", 2)

        setup_workspace = QWidget()
        setup_workspace.setObjectName("setupWorkspace")
        setup_workspace_layout = QBoxLayout(QBoxLayout.LeftToRight)
        setup_workspace_layout.setContentsMargins(0, 0, 0, 0)
        setup_workspace_layout.setSpacing(Spacing.LG)
        setup_workspace.setLayout(setup_workspace_layout)
        self._setup_workspace_layout = setup_workspace_layout

        prepare_stage = WorkflowStageCard(
            1,
            "Prepare the translation workspace",
            "Import the Step 0 selection or remove translated output before restarting.",
        )
        prepare_actions = QHBoxLayout()
        prepare_actions.setSpacing(Spacing.SM)

        import_btn = _make_btn("↓  Import files", "#5a5a60")
        import_btn.setToolTip("Import the files currently selected in Step 0")
        import_btn.setEnabled(False)
        import_btn.clicked.connect(lambda _checked=False: self._import_files())
        self._register_import_button(import_btn)
        prepare_actions.addWidget(import_btn)

        clear_translated_btn = _make_btn("✕  Clear translated", "#cc4444")
        clear_translated_btn.setToolTip("Delete translated/ contents after confirmation")
        clear_translated_btn.clicked.connect(self._clear_translated)
        _equalize_action_buttons(
            import_btn,
            clear_translated_btn,
            width=Geometry.ACTION_WIDE,
        )
        prepare_actions.addWidget(clear_translated_btn)
        prepare_actions.setStretch(0, 1)
        prepare_actions.setStretch(1, 1)
        prepare_actions.addStretch()
        prepare_stage.add_layout(prepare_actions)
        setup_workspace_layout.addWidget(prepare_stage, 2, Qt.AlignTop)

        speaker_stage = WorkflowStageCard(
            2,
            "Configure speakers and generate project context",
            "Collect recognized names first, then ask your AI helper whether this game needs any extra speaker formats.",
        )

        self.speaker_setup_hint = StatusBanner(
            "Always start with “1  Collect names” so recognized speakers are added to the "
            "Glossary. Next, run the setup instructions with your AI helper. If it marks an "
            "option ENABLE, turn that option on and collect names again. Many games need none.",
            "info",
        )
        speaker_stage.add_widget(self.speaker_setup_hint)

        flags_label = QLabel("SPEAKER NAME FORMATS")
        flags_label.setObjectName("workflowFieldCaption")
        speaker_stage.add_widget(flags_label)
        flags_grid = QGridLayout()
        flags_grid.setContentsMargins(0, 0, 0, 0)
        flags_grid.setHorizontalSpacing(Spacing.MD)
        flags_grid.setVerticalSpacing(Spacing.SM)

        self.spk_inline_cb = QCheckBox("Name is attached to the dialogue")
        self.spk_inline_cb.setToolTip(
            "Turn this on only when the setup helper says INLINE401SPEAKERS: ENABLE. "
            "Use it when the speaker's name touches the beginning of the dialogue."
        )
        self.spk_inline_cb.stateChanged.connect(self._apply_speaker_flags)
        flags_grid.addWidget(self.spk_inline_cb, 0, 0)
        inline_example = QLabel(
            "Example: エレナ「…」  ·  Helper says INLINE401SPEAKERS: ENABLE"
        )
        inline_example.setWordWrap(True)
        inline_example.setStyleSheet(f"color:{COLORS.text_muted};font-size:12px;")
        flags_grid.addWidget(inline_example, 0, 1)

        self.spk_firstline_cb = QCheckBox("Name is alone on the first dialogue line")
        self.spk_firstline_cb.setToolTip(
            "Turn this on only when the setup helper says FIRSTLINESPEAKERS: ENABLE. "
            "Use it when a short speaker name is on its own line above the dialogue."
        )
        self.spk_firstline_cb.stateChanged.connect(self._apply_speaker_flags)
        flags_grid.addWidget(self.spk_firstline_cb, 1, 0)
        firstline_example = QLabel(
            "Example: the first line contains only エレナ  ·  Helper says FIRSTLINESPEAKERS: ENABLE"
        )
        firstline_example.setWordWrap(True)
        firstline_example.setStyleSheet(f"color:{COLORS.text_muted};font-size:12px;")
        flags_grid.addWidget(firstline_example, 1, 1)

        self.spk_face_cb = QCheckBox("Use the face image's filename")
        self.spk_face_cb.setToolTip(
            "Turn this on only when the setup helper says FACENAME101: ENABLE. "
            "This last-resort option guesses the speaker from the face picture's filename."
        )
        self.spk_face_cb.stateChanged.connect(self._apply_speaker_flags)
        flags_grid.addWidget(self.spk_face_cb, 2, 0)
        face_example = QLabel(
            "Last resort only  ·  Helper says FACENAME101: ENABLE"
        )
        face_example.setWordWrap(True)
        face_example.setStyleSheet(f"color:{COLORS.text_muted};font-size:12px;")
        flags_grid.addWidget(face_example, 2, 1)
        flags_grid.setColumnStretch(0, 2)
        flags_grid.setColumnStretch(1, 3)
        speaker_stage.add_layout(flags_grid)

        context_actions = QHBoxLayout()
        context_actions.setSpacing(Spacing.SM)

        self.speaker_collect_names_btn = _make_btn("🔍  1  Collect names", "#0e639c")
        self.speaker_collect_names_btn.setToolTip(
            "Start here. Collect recognized speaker names from event files into the "
            "Glossary's # Speakers section. Run this again if you later enable an extra format."
        )
        self.speaker_collect_names_btn.clicked.connect(self._run_parse_speakers)
        context_actions.addWidget(self.speaker_collect_names_btn, 1)

        self.speaker_copy_setup_btn = _make_btn("📋  2  Copy setup instructions", "#555")
        self.speaker_copy_setup_btn.setToolTip(
            "After collecting names, paste these instructions into the AI helper with the game "
            "folder open. It will recommend any extra speaker options and return glossary, "
            "translation_quirks, game_skill, and RPG Maker configuration recommendations."
        )
        self.speaker_copy_setup_btn.clicked.connect(self._copy_project_setup_prompt)
        _equalize_action_buttons(
            self.speaker_collect_names_btn,
            self.speaker_copy_setup_btn,
            width=Geometry.ACTION_WIDE,
        )
        context_actions.addWidget(self.speaker_copy_setup_btn, 1)
        context_actions.addStretch()
        speaker_stage.add_layout(context_actions)
        setup_workspace_layout.addWidget(speaker_stage, 3, Qt.AlignTop)
        layout.addWidget(setup_workspace)
        self._populate_speaker_flags()

        guidance_stage = WorkflowStageCard(
            3,
            "Edit glossary, translation quirks, and game skill",
            "Keep the Glossary concise, record translation quirks, and review the generated game skill.",
        )
        self.setup_editors = SetupSkillsEditors(
            self,
            game_root_fn=lambda: self.folder_edit.text().strip(),
            log_fn=self._log,
        )
        guidance_stage.add_widget(self.setup_editors, 1)
        layout.addWidget(guidance_stage, 1)
        self.setup_editors.reload_all()


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
            self._log("   collected and added to the Glossary (# Speakers).")
            self._log("─" * 54)

        except Exception as exc:
            self._log(f"❌ _run_parse_speakers error: {exc}")
            return

        # 3. Select event files and auto-start
        self._navigate_to_translation("events", auto_start=True)

    # ── Step 2: Speaker Detection ───────────────────────────────────────────

    # ── Step 4: Translation ─────────────────────────────────────────────────

    def _add_tl_mode_selector(self, layout: QVBoxLayout | None = None):
        """Dropdown for normal vs batch TL; applies to all workflow phase run buttons."""
        mode_box = QWidget()
        mode_box.setObjectName("tbox")
        mode_box.setStyleSheet(self._task_box_style())
        mode_inner = QVBoxLayout(mode_box)
        mode_inner.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        mode_inner.setSpacing(Spacing.SM)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(Spacing.MD)
        mode_lbl = _make_form_label("Run mode:")
        mode_lbl.setStyleSheet("color:#c8c8c8;font-size:13px;font-weight:bold;")
        self._tl_mode_combo = QComboBox()
        self._tl_mode_combo.addItem(WORKFLOW_TL_NORMAL_LABEL)
        self._tl_mode_combo.addItem(BATCH_MODE_LABEL)
        self._tl_mode_combo.setMinimumWidth(Geometry.FIELD_MEDIUM)
        self._tl_mode_combo.setToolTip(
            "Applies to Phase 0, 1, 1b, and 2 run buttons. "
            "Batch uses the Anthropic Batches API (50% off, Claude only)."
        )
        self._tl_mode_combo.currentTextChanged.connect(self._on_workflow_tl_mode_changed)
        self._tl_mode_combo.activated.connect(self._mark_workflow_tl_mode_selected)
        mode_row.addWidget(mode_lbl)
        mode_row.addWidget(self._tl_mode_combo)
        mode_row.addStretch()
        mode_inner.addLayout(mode_row)

        self._batch_mode_benefit = QLabel(BATCH_MODE_BENEFIT_NOTE)
        self._batch_mode_benefit.setWordWrap(True)
        self._batch_mode_benefit.setStyleSheet("color:#73c991;font-size:12px;")
        self._batch_mode_benefit.setVisible(False)
        mode_inner.addWidget(self._batch_mode_benefit)

        self._batch_mode_warning = QLabel(BATCH_COLLECT_LIVE_CHARGE_NOTE)
        self._batch_mode_warning.setWordWrap(True)
        self._batch_mode_warning.setStyleSheet("color:#f2c94c;font-size:11px;")
        self._batch_mode_warning.setVisible(False)
        mode_inner.addWidget(self._batch_mode_warning)

        if layout is not None:
            layout.addWidget(mode_box)
        self.refresh_default_translation_mode(force=True)
        self._on_workflow_tl_mode_changed(self._tl_mode_combo.currentText())
        return mode_box

    def _on_workflow_tl_mode_changed(self, mode_text: str):
        is_batch = mode_text == BATCH_MODE_LABEL
        if hasattr(self, "_batch_mode_benefit"):
            self._batch_mode_benefit.setVisible(is_batch)
        if hasattr(self, "_batch_mode_warning"):
            self._batch_mode_warning.setVisible(is_batch)
        if hasattr(self, "_step5_mode_hint"):
            self._step5_mode_hint.setText(f"Run mode: {mode_text}")
            if is_batch:
                self._step5_mode_hint.setStyleSheet("color:#73c991;font-size:12px;margin-bottom:4px;")
            else:
                self._step5_mode_hint.setStyleSheet("color:#a6a6a6;font-size:12px;margin-bottom:4px;")

    def _workflow_batch_mode(self) -> bool:
        combo = getattr(self, "_tl_mode_combo", None)
        return combo is not None and combo.currentText() == BATCH_MODE_LABEL

    def _mark_workflow_tl_mode_selected(self, _index: int):
        self._tl_mode_user_selected = True

    def refresh_default_translation_mode(self, force=False):
        """Refresh the workflow mode when the configured provider changes."""
        default_mode = default_translation_mode()
        if not force and default_mode == self._last_default_translation_mode:
            return
        self._last_default_translation_mode = default_mode
        workflow_mode = (
            BATCH_MODE_LABEL if default_mode == BATCH_MODE_LABEL else WORKFLOW_TL_NORMAL_LABEL
        )
        if default_mode == "Translate" or force or not self._tl_mode_user_selected:
            index = self._tl_mode_combo.findText(workflow_mode)
            if index >= 0:
                self._tl_mode_combo.setCurrentIndex(index)

    def _workflow_mode_text(self) -> str:
        return BATCH_MODE_LABEL if self._workflow_batch_mode() else "Translate"

    def _build_step4_translation(self, layout: QVBoxLayout):

        self._add_step_header(layout, "Step 3 — Translation · Phase 1", 3)

        preflight_stage = WorkflowStageCard(
            1,
            "Set run mode and line widths",
            "These settings apply to every translation action below and define the game's line-length limits.",
        )
        preflight_stage.add_widget(self._add_tl_mode_selector())

        # ---- Pre-flight: text wrap configuration ----------------------------
        wrap_box_title = QLabel("Line widths (characters)")
        wrap_box_title.setStyleSheet("color:#f2f2f2;font-size:13px;font-weight:bold;")
        wrap_box = QWidget()
        wrap_box.setObjectName("tbox")
        wrap_box.setStyleSheet(self._task_box_style())
        wrap_inner = QVBoxLayout(wrap_box)
        wrap_inner.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        wrap_inner.setSpacing(Spacing.XS)
        wrap_inner.addWidget(wrap_box_title)

        wrap_hint = QLabel(
            "These values reload directly from .env when this page is shown. Saving writes the "
            "dialogue, face-dialogue, list/help, and note limits back to .env; font recommendations "
            "are not applied here."
        )
        wrap_hint.setWordWrap(True)
        wrap_hint.setStyleSheet("color:#a6a6a6;font-size:13px;")
        wrap_inner.addWidget(wrap_hint)

        # Shared columns keep labels, values, and the apply action aligned.
        spins_grid = QGridLayout()
        spins_grid.setHorizontalSpacing(Spacing.MD)
        spins_grid.setVerticalSpacing(Spacing.XS)

        def _spin_pair(label_text: str, default: int):
            lbl = QLabel(label_text)
            lbl.setObjectName("workflowFieldCaption")
            sp = QSpinBox()
            sp.setRange(20, 300)
            sp.setValue(default)
            sp.setMinimumWidth(Geometry.FIELD_COMPACT)
            sp.setMaximumWidth(160)
            return lbl, sp

        lbl_w,  self.wrap_width_spin = _spin_pair("Dialogue", 60)
        lbl_fw, self.wrap_face_spin  = _spin_pair("With face", 50)
        self.wrap_face_spin.setMaximum(self.wrap_width_spin.value())
        self.wrap_width_spin.valueChanged.connect(self.wrap_face_spin.setMaximum)
        lbl_lw, self.wrap_list_spin  = _spin_pair("Lists & help", 70)
        lbl_nw, self.wrap_note_spin  = _spin_pair("Notes", 60)

        for column, (lbl, sp) in enumerate(
            (
                (lbl_w, self.wrap_width_spin),
                (lbl_fw, self.wrap_face_spin),
                (lbl_lw, self.wrap_list_spin),
                (lbl_nw, self.wrap_note_spin),
            )
        ):
            spins_grid.addWidget(lbl, 0, column)
            spins_grid.addWidget(sp, 1, column)
            spins_grid.setColumnStretch(column, 1)

        apply_wrap_btn = _make_btn("✔  Save line widths", "#0e639c")
        _size_action_button(apply_wrap_btn, Geometry.ACTION_WIDE)
        apply_wrap_btn.setToolTip(
            "Write width / faceWidth / listWidth / noteWidth into .env"
        )
        apply_wrap_btn.clicked.connect(self._apply_wrap_config)
        spins_grid.addWidget(apply_wrap_btn, 1, 4)

        wrap_inner.addLayout(spins_grid)
        preflight_stage.add_widget(wrap_box)
        layout.addWidget(preflight_stage)

        # ---- Phase 0 --------------------------------------------------------
        p0_box = WorkflowStageCard(
            2,
            "Translate database text",
            "Translate names, descriptions, and notes in the core database before translating event text.",
        )
        p0_inner = p0_box.body
        p0_row = QHBoxLayout()
        p0_row.setSpacing(Spacing.MD)
        self._run_p0_btn = _make_btn("►  Translate database", "#0e639c")
        _size_action_button(self._run_p0_btn, Geometry.ACTION_WIDE)
        self._run_p0_btn.setToolTip(
            "Phase 0: select core database files, disable event codes, and start translation"
        )
        self._run_p0_btn.clicked.connect(lambda: self._run_phase(0))
        p0_row.addWidget(self._run_p0_btn)
        self._p0_status_lbl = QLabel("")
        self._p0_status_lbl.setStyleSheet("color:#73c991;font-size:13px;padding-left:4px;")
        p0_row.addWidget(self._p0_status_lbl)
        p0_row.addStretch()
        p0_inner.addLayout(p0_row)
        layout.addWidget(p0_box)

        # ---- Phase 1 --------------------------------------------------------
        p1_box = WorkflowStageCard(
            3,
            "Translate dialogue and choices",
            "Translate names, messages, scrolling text, and choices. Include code 408 only when an enabled plugin displays it.",
        )
        p1_inner = p1_box.body
        self._phase1_code408_cb = QCheckBox(
            "Include displayed comment text (code 408)"
        )
        saved_408 = self._setting("phase1_code408", False)
        if isinstance(saved_408, str):
            saved_408 = saved_408.strip().casefold() in {"1", "true", "yes", "on"}
        self._phase1_code408_cb.setChecked(bool(saved_408))
        self._phase1_code408_cb.setToolTip(
            "Enable only when Project Setup finds an enabled plugin that displays text from "
            "108/408 comment blocks. Leave off for ordinary editor comments."
        )
        self._phase1_code408_cb.stateChanged.connect(
            lambda state: self._save_setting("phase1_code408", bool(state))
        )
        p1_inner.addWidget(self._phase1_code408_cb)
        p1_row = QHBoxLayout()
        p1_row.setSpacing(Spacing.MD)
        self._run_p1_btn = _make_btn("►  Translate dialogue", "#0e639c")
        _size_action_button(self._run_p1_btn, Geometry.ACTION_WIDE)
        self._run_p1_btn.setToolTip("Phase 1: select event files and translate dialogue and choices")
        self._run_p1_btn.clicked.connect(lambda: self._run_phase(1))
        p1_row.addWidget(self._run_p1_btn)
        self._p1_status_lbl = QLabel("")
        self._p1_status_lbl.setStyleSheet("color:#75beff;font-size:13px;padding-left:4px;")
        p1_row.addWidget(self._p1_status_lbl)
        p1_row.addStretch()
        p1_inner.addLayout(p1_row)
        layout.addWidget(p1_box)

        # ---- Phase 1b -------------------------------------------------------
        p1b_box = WorkflowStageCard(
            4,
            "Build the variable translation cache",
            "Translate code 111 variable comparisons and cache them for matching code 122 text in Phase 2.",
        )
        p1b_inner = p1b_box.body
        p1b_row = QHBoxLayout()
        p1b_row.setSpacing(Spacing.MD)
        self._run_p1b_btn = _make_btn("►  Build variable cache", "#0e639c")
        _size_action_button(self._run_p1b_btn, Geometry.ACTION_WIDE)
        self._run_p1b_btn.setToolTip("Phase 1b: translate code 111 comparisons and build the variable cache")
        self._run_p1b_btn.clicked.connect(lambda: self._run_phase("1b"))
        p1b_row.addWidget(self._run_p1b_btn)
        self._p1b_status_lbl = QLabel("")
        self._p1b_status_lbl.setStyleSheet("color:#75beff;font-size:13px;padding-left:4px;")
        p1b_row.addWidget(self._p1b_status_lbl)
        p1b_row.addStretch()
        p1b_inner.addLayout(p1b_row)
        layout.addWidget(p1b_box)
        equalize_button_widths(
            (
                apply_wrap_btn,
                self._run_p0_btn,
                self._run_p1_btn,
                self._run_p1b_btn,
            ),
            minimum=Geometry.ACTION_WIDE,
            maximum=Geometry.ACTION_WIDE,
        )

    def _build_step5_tl_phase2(self, layout: QVBoxLayout):

        self._add_step_header(layout, "Step 4 — Translation · Phase 2", 4)
        audit_stage = WorkflowStageCard(
            1,
            "Audit advanced text sources",
            "Identify player-visible variable, plugin, and script text before enabling any source below.",
        )

        initial_mode = getattr(self, "_tl_mode_combo", None)
        initial_mode_text = initial_mode.currentText() if initial_mode is not None else WORKFLOW_TL_NORMAL_LABEL
        self._step5_mode_hint = QLabel(f"Run mode: {initial_mode_text}")
        self._step5_mode_hint.setStyleSheet("color:#73c991;font-size:12px;margin-bottom:4px;")
        audit_stage.add_widget(self._step5_mode_hint)
        if hasattr(self, "_tl_mode_combo"):
            self._on_workflow_tl_mode_changed(self._tl_mode_combo.currentText())

        # ── Pre-flight card: description + prompt + var range ──────────────
        pre_box = QWidget()
        pre_box.setObjectName("tbox")
        pre_box.setStyleSheet(self._task_box_style())
        pre_inner = QVBoxLayout(pre_box)
        pre_inner.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        pre_inner.setSpacing(Spacing.SM)

        pre_top = QHBoxLayout()
        pre_top.setSpacing(Spacing.MD)
        desc_lbl = QLabel(
            "This phase can touch logic-adjacent text. Audit first, then enable only sources "
            "confirmed to contain player-visible text."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color:#a6a6a6;font-size:13px;")
        pre_top.addWidget(desc_lbl, 1)
        copy_risky_btn = _make_btn("📋  Copy advanced-text audit", "#555")
        _size_action_button(copy_risky_btn, Geometry.ACTION_WIDE)
        copy_risky_btn.setToolTip(
            "Copy a Copilot prompt that audits code 122 variable ranges and all optional "
            "plugin/script codes for visible text."
        )
        copy_risky_btn.clicked.connect(self._copy_plugin_prompt)
        pre_top.addWidget(copy_risky_btn)
        pre_inner.addLayout(pre_top)
        self._p2_ai_help_banner = StatusBanner(
            "How to use this: click Copy advanced-text audit, paste the copied instructions "
            "into your AI helper with the game folder open, then return here and enable only "
            "the text sources it confirms are used by players.",
            "info",
        )
        pre_inner.addWidget(self._p2_ai_help_banner)
        audit_stage.add_widget(pre_box)
        layout.addWidget(audit_stage)

        # ── Code toggles ───────────────────────────────────────────────────
        codes_stage = WorkflowStageCard(
            2,
            "Select audited text sources",
            "Keep uncertain sources off. Fine-grained plugin and script filters are available under Advanced.",
        )
        codes_hdr = QHBoxLayout()
        codes_title_lbl = QLabel("Event command types")
        codes_title_lbl.setStyleSheet("color:#f2f2f2;font-size:13px;font-weight:bold;")
        codes_hdr.addWidget(codes_title_lbl)
        codes_hdr.addStretch()
        clear_codes_btn = _make_btn("Clear selections", "#555")
        _size_action_button(
            clear_codes_btn,
            Geometry.FIELD_COMPACT,
            maximum=160,
        )
        clear_codes_btn.setToolTip("Turn off every advanced event command type")
        codes_hdr.addWidget(clear_codes_btn)
        codes_stage.add_layout(codes_hdr)

        toggle_box = QWidget()
        toggle_box.setObjectName("cbbox")
        toggle_box.setStyleSheet(self._checkbox_box_style())
        toggle_box_layout = QVBoxLayout(toggle_box)
        toggle_box_layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.MD, Spacing.SM)
        toggle_box_layout.setSpacing(Spacing.XS)

        toggle_grid_container = QWidget()
        toggle_grid = QGridLayout(toggle_grid_container)
        toggle_grid.setContentsMargins(0, 0, 0, 0)
        toggle_grid.setHorizontalSpacing(24)
        toggle_grid.setVerticalSpacing(4)

        _P2_CODE_DEFS = [
            ("CODE122",    "Variables (122)",           "Control Variables (code 122)"),
            ("CODE357",    "MZ plugin commands (357)",  "MZ Plugin Command text (code 357)"),
            ("CODE355655", "Scripts (355/655)",         "Inline script text (codes 355/655)"),
            ("CODE356",    "MV plugin commands (356)",  "MV Plugin Command text (code 356)"),
            ("CODE657",    "Picture text (657)",        "Extended picture text (code 657)"),
            ("CODE320",    "Actor names (320)",         "Change Actor Name (code 320)"),
            ("CODE324",    "Nicknames (324)",           "Change Nickname (code 324)"),
            ("CODE325",    "Profiles (325)",            "Change Profile (code 325)"),
            ("CODE108",    "Comment notetags (108)",    "Comment notetags (code 108)"),
        ]
        self._p2_code_checks: dict = {}
        for idx, (code_key, label, tip) in enumerate(_P2_CODE_DEFS):
            cb = QCheckBox(label)
            cb.setToolTip(tip)
            cb.setStyleSheet(
                f"QCheckBox{{color:{COLORS.text_secondary};font-size:13px;}}"
                f"QCheckBox:disabled{{color:{COLORS.text_disabled};}}"
            )
            toggle_grid.addWidget(cb, idx // 3, idx % 3)
            cb.stateChanged.connect(self._schedule_p2_config_apply)
            self._p2_code_checks[code_key] = cb
        for column in range(3):
            toggle_grid.setColumnStretch(column, 1)
        toggle_box_layout.addWidget(toggle_grid_container)

        def _clear_codes():
            for cb in self._p2_code_checks.values():
                cb.setChecked(False)
        clear_codes_btn.clicked.connect(_clear_codes)
        codes_stage.add_widget(toggle_box)

        # Code 122 owns the variable range. Keeping this control beside its
        # parent checkbox makes the dependency visible and allows the entire
        # row to disable when Variables (122) is off.
        self._p2_var_range_box = QFrame()
        self._p2_var_range_box.setObjectName("phase2VariableRange")
        self._p2_var_range_box.setStyleSheet(
            f"QFrame#phase2VariableRange{{background:{COLORS.chrome};"
            f"border:1px solid {COLORS.border};border-radius:4px;}}"
            f"QFrame#phase2VariableRange QLabel{{background:transparent;border:none;}}"
        )
        var_row = QHBoxLayout(self._p2_var_range_box)
        var_row.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        var_row.setSpacing(Spacing.SM)
        var_lbl = _make_form_label("Variable IDs:")
        var_row.addWidget(var_lbl)
        from PyQt5.QtGui import QIntValidator
        self._p2_var_min = QLineEdit("0")
        self._p2_var_min.setValidator(QIntValidator(0, 99999))
        self._p2_var_min.setFixedWidth(88)
        self._p2_var_min.setAlignment(Qt.AlignCenter)
        self._p2_var_min.setToolTip("Minimum variable ID to translate (inclusive)")
        var_row.addWidget(self._p2_var_min)
        dash_lbl = QLabel("–")
        dash_lbl.setStyleSheet("color:#a6a6a6;")
        var_row.addWidget(dash_lbl)
        self._p2_var_max = QLineEdit("2000")
        self._p2_var_max.setValidator(QIntValidator(1, 99999))
        self._p2_var_max.setFixedWidth(88)
        self._p2_var_max.setAlignment(Qt.AlignCenter)
        self._p2_var_max.setToolTip("Maximum variable ID to translate (exclusive)")
        var_row.addWidget(self._p2_var_max)
        apply_range_btn = _make_btn("Save range", "#45454a")
        _size_action_button(apply_range_btn, Geometry.FIELD_COMPACT, maximum=160)
        apply_range_btn.setToolTip("Save the variable range used by Variables (122)")
        apply_range_btn.clicked.connect(self._apply_var_range)
        var_row.addWidget(apply_range_btn)
        self._p2_var_min.editingFinished.connect(self._schedule_p2_config_apply)
        self._p2_var_max.editingFinished.connect(self._schedule_p2_config_apply)
        var_hint = QLabel("Available only when Variables (122) is enabled.")
        var_hint.setWordWrap(True)
        var_hint.setStyleSheet(f"color:{COLORS.text_muted};font-size:12px;")
        var_row.addWidget(var_hint, 1)
        codes_stage.add_widget(self._p2_var_range_box)

        # ── 357 plugins + 355/655 patterns — side by side ──────────────────
        lists_container = QWidget()
        lists_container.setObjectName("phase2AdvancedLists")
        lists_container.setStyleSheet(
            "QWidget#phase2AdvancedLists{background:transparent;}"
        )
        lists_row = QHBoxLayout(lists_container)
        lists_row.setContentsMargins(0, 0, 0, 0)
        lists_row.setSpacing(Spacing.SM)

        # Left column: header row + group box
        self._p2_plugin_filter_group = QWidget()
        self._p2_plugin_filter_group.setObjectName("phase2PluginFilters")
        self._p2_plugin_filter_group.setStyleSheet(
            "QWidget#phase2PluginFilters{background:transparent;}"
        )
        left_col = QVBoxLayout(self._p2_plugin_filter_group)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(Spacing.XS)

        plugin357_hdr = QHBoxLayout()
        plugin357_title_lbl = QLabel("MZ plugin command filters")
        plugin357_title_lbl.setStyleSheet("color:#f2f2f2;font-size:13px;font-weight:bold;")
        plugin357_hdr.addWidget(plugin357_title_lbl)
        plugin357_hdr.addStretch()
        clear_plugins357_btn = _make_btn("Clear handlers", "#555")
        _size_action_button(
            clear_plugins357_btn,
            Geometry.FIELD_COMPACT,
            maximum=160,
        )
        clear_plugins357_btn.setToolTip("Turn off every MZ plugin handler")
        plugin357_hdr.addWidget(clear_plugins357_btn)
        left_col.addLayout(plugin357_hdr)
        plugin357_caption = QLabel(
            "Used only when MZ plugin commands (357) is enabled above."
        )
        plugin357_caption.setWordWrap(True)
        plugin357_caption.setStyleSheet(
            f"color:{COLORS.text_muted};font-size:12px;background:transparent;"
        )
        left_col.addWidget(plugin357_caption)

        plugin357_box = QWidget()
        plugin357_box.setObjectName("cbbox")
        plugin357_box.setStyleSheet(self._checkbox_box_style())
        plugin357_inner = QVBoxLayout(plugin357_box)
        plugin357_inner.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.MD, Spacing.SM)
        plugin357_inner.setSpacing(Spacing.XS)

        plugin357_container = QWidget()
        plugin357_vbox = QVBoxLayout(plugin357_container)
        plugin357_vbox.setContentsMargins(Spacing.XS, Spacing.XS, Spacing.XS, Spacing.XS)
        plugin357_vbox.setSpacing(Spacing.XS)
        self._p2_plugin_checks: dict = {}
        try:
            from modules.rpgmakermvmz import HEADER_MAPPINGS_357 as _HM357
            for key in sorted(_HM357.keys(), key=str.casefold):
                cb = QCheckBox(key)
                cb.setStyleSheet(
                    f"QCheckBox{{color:{COLORS.text_secondary};font-size:13px;}}"
                    f"QCheckBox:disabled{{color:{COLORS.text_disabled};}}"
                )
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

        def _clear_plugins357():
            for cb in self._p2_plugin_checks.values():
                cb.setChecked(False)
        clear_plugins357_btn.clicked.connect(_clear_plugins357)

        left_col.addWidget(plugin357_box, 1)
        lists_row.addWidget(self._p2_plugin_filter_group, 1)

        # Right column: header row + group box
        self._p2_pattern_filter_group = QWidget()
        self._p2_pattern_filter_group.setObjectName("phase2ScriptFilters")
        self._p2_pattern_filter_group.setStyleSheet(
            "QWidget#phase2ScriptFilters{background:transparent;}"
        )
        right_col = QVBoxLayout(self._p2_pattern_filter_group)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(Spacing.XS)

        patterns_hdr = QHBoxLayout()
        patterns_title_lbl = QLabel("Script text filters")
        patterns_title_lbl.setStyleSheet("color:#f2f2f2;font-size:13px;font-weight:bold;")
        patterns_hdr.addWidget(patterns_title_lbl)
        patterns_hdr.addStretch()
        clear_patterns_btn = _make_btn("Clear patterns", "#555")
        _size_action_button(
            clear_patterns_btn,
            Geometry.FIELD_COMPACT,
            maximum=160,
        )
        clear_patterns_btn.setToolTip("Turn off every script pattern")
        patterns_hdr.addWidget(clear_patterns_btn)
        right_col.addLayout(patterns_hdr)
        patterns_caption = QLabel(
            "Used only when Scripts (355/655) is enabled above."
        )
        patterns_caption.setWordWrap(True)
        patterns_caption.setStyleSheet(
            f"color:{COLORS.text_muted};font-size:12px;background:transparent;"
        )
        right_col.addWidget(patterns_caption)

        patterns_box = QWidget()
        patterns_box.setObjectName("cbbox")
        patterns_box.setStyleSheet(self._checkbox_box_style())
        patterns_inner_layout = QVBoxLayout(patterns_box)
        patterns_inner_layout.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.MD, Spacing.SM)
        patterns_inner_layout.setSpacing(Spacing.XS)

        patterns_container = QWidget()
        patterns_vbox = QVBoxLayout(patterns_container)
        patterns_vbox.setContentsMargins(Spacing.XS, Spacing.XS, Spacing.XS, Spacing.XS)
        patterns_vbox.setSpacing(Spacing.XS)
        self._p2_pattern_checks: dict = {}
        try:
            from modules.rpgmakermvmz import PATTERNS_355655 as _PAT
            for key in sorted(_PAT.keys(), key=str.casefold):
                cb = QCheckBox(key)
                cb.setStyleSheet(
                    f"QCheckBox{{color:{COLORS.text_secondary};font-size:13px;}}"
                    f"QCheckBox:disabled{{color:{COLORS.text_disabled};}}"
                )
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

        def _clear_patterns():
            for cb in self._p2_pattern_checks.values():
                cb.setChecked(False)
        clear_patterns_btn.clicked.connect(_clear_patterns)
        equalize_button_widths(
            (
                clear_codes_btn,
                apply_range_btn,
                clear_plugins357_btn,
                clear_patterns_btn,
            ),
            minimum=144,
            maximum=144,
        )

        right_col.addWidget(patterns_box, 1)
        lists_row.addWidget(self._p2_pattern_filter_group, 1)

        self._p2_advanced_hint = QLabel(
            "Advanced filters stay locked until their matching text source is enabled above."
        )
        self._p2_advanced_hint.setWordWrap(True)
        self._p2_advanced_hint.setStyleSheet(
            f"color:{COLORS.text_muted};font-size:12px;"
        )
        codes_stage.add_widget(self._p2_advanced_hint)

        self._phase2_advanced = DisclosureSection(
            "Advanced plugin and script filters",
            lists_container,
            expanded=False,
        )
        self._phase2_advanced.toggle.setToolTip(
            "Opens after MZ plugin commands (357) or Scripts (355/655) is enabled"
        )
        codes_stage.add_widget(self._phase2_advanced)
        for key in ("CODE122", "CODE357", "CODE355655"):
            self._p2_code_checks[key].toggled.connect(
                self._refresh_p2_control_dependencies
            )
        layout.addWidget(codes_stage)

        # ── Bottom row: Run ────────────────────────────────────────────────
        run_stage = WorkflowStageCard(
            3,
            "Start advanced translation",
            "Apply the selected sources, select event files, and begin translation.",
        )
        self._p2_selection_banner = StatusBanner(
            "Select at least one audited event command type above.",
            "warning",
        )
        run_stage.add_widget(self._p2_selection_banner)
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(Spacing.MD)
        self._run_p2_btn = _make_btn("►  Translate selected text", "#7a4a00")
        _size_action_button(self._run_p2_btn, Geometry.ACTION_WIDE)
        self._run_p2_btn.setToolTip(
            "Applies Phase 2 code settings and starts translation with event files pre-selected."
        )
        self._run_p2_btn.clicked.connect(lambda: self._run_phase(2))
        bottom_row.addWidget(self._run_p2_btn)

        self._p2_status_lbl = QLabel("")
        self._p2_status_lbl.setStyleSheet("color:#f2c94c;font-size:13px;padding-left:4px;")
        bottom_row.addWidget(self._p2_status_lbl)
        bottom_row.addStretch()
        run_stage.add_layout(bottom_row)
        layout.addWidget(run_stage)

        self._p2_auto_apply_timer = QTimer(self)
        self._p2_auto_apply_timer.setSingleShot(True)
        self._p2_auto_apply_timer.timeout.connect(self._apply_p2_config)

        equalize_button_widths(
            (copy_risky_btn, self._run_p2_btn),
            minimum=Geometry.ACTION_WIDE,
            maximum=Geometry.ACTION_WIDE,
        )

        # Pre-populate all Phase 2 checkboxes from current module state
        self._populate_p2_checkboxes()

    # ── Step 6: Rewrap exported game data ─────────────────────────────────

    def _build_step5_rewrap(self, layout: QVBoxLayout):
        self._add_step_header(layout, "Step 6 — Rewrap & Release", 6)

        source_banner = StatusBanner(
            "Complete Step 0 and export in Step 5 to load the game data source.",
            "info",
        )
        self.rewrap_scope_title = source_banner.text_label
        layout.addWidget(source_banner)

        workspace = QWidget()
        workspace.setObjectName("rewrapWorkspace")
        workspace_layout = QBoxLayout(QBoxLayout.LeftToRight)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(Spacing.LG)
        workspace.setLayout(workspace_layout)
        self._rewrap_workspace_layout = workspace_layout

        # Stage 1 — scope first. The source path has its own banner above, so it
        # never competes with filtering or wraps into a narrow pseudo-heading.
        scope_stage = WorkflowStageCard(
            1,
            "Select game-data files",
            "Choose a preset, then refine the selected JSON files if needed.",
        )

        scope_presets = QHBoxLayout()
        scope_presets.setSpacing(Spacing.SM)
        scope_preset_buttons: list[QPushButton] = []
        for label_text, mode, tooltip in (
            ("Select all", "all", "Select every JSON file in the detected game-data folder"),
            ("Maps & events", "events", "Select maps, CommonEvents, and Troops"),
            ("Database only", "db", "Select core database files"),
            ("Clear selection", "none", "Deselect every file"),
        ):
            button = _make_text_btn(label_text, tooltip, min_width=128)
            button.clicked.connect(
                lambda _checked=False, selected_mode=mode: self._select_rewrap_files(
                    selected_mode
                )
            )
            scope_presets.addWidget(button)
            scope_preset_buttons.append(button)
        _equalize_action_buttons(
            *scope_preset_buttons,
            width=144,
            maximum=208,
        )
        for column in range(len(scope_preset_buttons)):
            scope_presets.setStretch(column, 1)
        scope_presets.addStretch()
        scope_stage.add_layout(scope_presets)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(Spacing.SM)
        self.rewrap_file_filter = QLineEdit()
        self.rewrap_file_filter.setPlaceholderText("Filter files by name…")
        self.rewrap_file_filter.setClearButtonEnabled(True)
        self.rewrap_file_filter.textChanged.connect(self._filter_rewrap_files)
        filter_row.addWidget(self.rewrap_file_filter, 1)
        refresh_files_btn = _make_text_btn(
            "Refresh files", "Reload JSON filenames from the detected game-data folder", min_width=112
        )
        refresh_files_btn.clicked.connect(self._refresh_rewrap_files)
        filter_row.addWidget(refresh_files_btn)
        scope_stage.add_layout(filter_row)

        self.rewrap_file_list = CheckableFileList()
        self.rewrap_file_list.setMinimumHeight(280)
        self.rewrap_file_list.setStyleSheet(
            f"QListWidget{{background:{COLORS.chrome};border:1px solid {COLORS.border};"
            f"border-radius:4px;color:{COLORS.text_secondary};font-size:12px;padding:4px;}}"
            "QListWidget::item{padding:4px 6px;}"
        )
        scope_stage.add_widget(self.rewrap_file_list, 1)
        workspace_layout.addWidget(scope_stage, 3)

        # Stage 2 — rules are a compact vertical matrix instead of one long row.
        rules_stage = WorkflowStageCard(
            2,
            "Set line-wrapping rules",
            "Choose text categories and the maximum number of characters per line.",
        )
        rules_grid = QGridLayout()
        rules_grid.setContentsMargins(0, 0, 0, 0)
        rules_grid.setHorizontalSpacing(Spacing.MD)
        rules_grid.setVerticalSpacing(Spacing.SM)
        category_heading = QLabel("TEXT TYPE")
        category_heading.setObjectName("workflowFieldCaption")
        width_heading = QLabel("MAX CHARACTERS")
        width_heading.setObjectName("workflowFieldCaption")
        rules_grid.addWidget(category_heading, 0, 0)
        rules_grid.addWidget(width_heading, 0, 1)

        self.rewrap_dialogue_cb = QCheckBox("Dialogue without faces")
        self.rewrap_face_cb = QCheckBox("Dialogue with faces")
        self.rewrap_list_cb = QCheckBox("Lists & help text")
        self.rewrap_notes_cb = QCheckBox("Database notes")
        self.rewrap_notes_cb.setToolTip(
            "Rewrap only recognized player-facing prose bodies inside note tags; "
            "plugin syntax and other note metadata remain unchanged."
        )
        def _rewrap_width(value: int):
            spin = QSpinBox()
            spin.setRange(10, 300)
            spin.setValue(value)
            spin.setSuffix(" chars")
            spin.setMinimumWidth(112)
            return spin

        self.rewrap_dialogue_width = _rewrap_width(
            self.wrap_width_spin.value()
        )
        self.rewrap_face_width = _rewrap_width(
            self.wrap_face_spin.value()
        )
        self.rewrap_face_width.setMaximum(self.rewrap_dialogue_width.value())
        self.rewrap_dialogue_width.valueChanged.connect(
            self.rewrap_face_width.setMaximum
        )
        self.rewrap_list_width = _rewrap_width(self.wrap_list_spin.value())
        self.rewrap_note_width = _rewrap_width(self.wrap_note_spin.value())
        for row, (checkbox, spin) in enumerate(
            (
                (self.rewrap_dialogue_cb, self.rewrap_dialogue_width),
                (self.rewrap_face_cb, self.rewrap_face_width),
                (self.rewrap_list_cb, self.rewrap_list_width),
                (self.rewrap_notes_cb, self.rewrap_note_width),
            ),
            start=1,
        ):
            checkbox.setChecked(True)
            rules_grid.addWidget(checkbox, row, 0)
            rules_grid.addWidget(spin, row, 1)
        rules_grid.setColumnStretch(0, 1)
        rules_stage.add_layout(rules_grid)

        load_widths_btn = _make_text_btn(
            "Load saved line widths",
            "Load width / faceWidth / listWidth / noteWidth from .env",
            min_width=160,
        )
        load_widths_btn.clicked.connect(self._load_rewrap_widths)
        rules_stage.add_widget(load_widths_btn, 0)

        advanced_content = QWidget()
        advanced_layout = QVBoxLayout(advanced_content)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(Spacing.SM)
        code_label = QLabel("Event command codes")
        code_label.setObjectName("workflowFieldCaption")
        advanced_layout.addWidget(code_label)
        self.rewrap_codes_edit = QLineEdit("401,405")
        self.rewrap_codes_edit.setPlaceholderText("Leave blank to include every supported code")
        self.rewrap_codes_edit.setToolTip(
            "Restricts recognized event display fields only. Supported: 401/405 messages, "
            "122 stored list text, 324 list text, 325 profile/dialogue, and known 357 text keys. "
            "Database list/help and note fields are controlled by their category checkboxes."
        )
        advanced_layout.addWidget(self.rewrap_codes_edit)
        code_presets = QHBoxLayout()
        code_presets.setSpacing(Spacing.SM)
        standard_codes_btn = _make_text_btn(
            "Messages only", "Use standard Show Text and Scroll Text fields only", min_width=168
        )
        standard_codes_btn.clicked.connect(
            lambda: self.rewrap_codes_edit.setText("401,405")
        )
        code_presets.addWidget(standard_codes_btn)
        all_codes_btn = _make_text_btn(
            "All supported fields", "Include every recognized display-code field", min_width=168
        )
        all_codes_btn.clicked.connect(self.rewrap_codes_edit.clear)
        code_presets.addWidget(all_codes_btn)
        _equalize_action_buttons(
            standard_codes_btn,
            all_codes_btn,
            width=168,
            maximum=220,
        )
        code_presets.setStretch(0, 1)
        code_presets.setStretch(1, 1)
        code_presets.addStretch()
        advanced_layout.addLayout(code_presets)

        protection_row = QHBoxLayout()
        protection_row.setSpacing(Spacing.SM)
        self.rewrap_skip_overflow_cb = QCheckBox("Skip fields over row limit")
        self.rewrap_skip_overflow_cb.setChecked(True)
        self.rewrap_skip_overflow_cb.setToolTip(
            "When enabled, skip non-401 fields that exceed this row limit, including scrolling "
            "text, list/help, notes, and supported plugin fields. Code 401 and face-401 dialogue "
            "are never blocked."
        )
        protection_row.addWidget(self.rewrap_skip_overflow_cb)
        self.rewrap_max_rows_spin = QSpinBox()
        self.rewrap_max_rows_spin.setRange(1, 20)
        self.rewrap_max_rows_spin.setValue(4)
        self.rewrap_max_rows_spin.setSuffix(" rows")
        self.rewrap_max_rows_spin.setMinimumWidth(104)
        self.rewrap_max_rows_spin.setEnabled(True)
        self.rewrap_skip_overflow_cb.toggled.connect(
            self.rewrap_max_rows_spin.setEnabled
        )
        protection_row.addWidget(self.rewrap_max_rows_spin)
        protection_row.addStretch()
        advanced_layout.addLayout(protection_row)
        advanced = DisclosureSection(
            "Advanced event fields", advanced_content, expanded=False
        )
        self._rewrap_advanced = advanced
        rules_stage.add_widget(advanced)
        workspace_layout.addWidget(rules_stage, 2)
        layout.addWidget(workspace)

        # Stage 3 — scanning and applying now live with their status and output.
        review_stage = WorkflowStageCard(
            3,
            "Preview and apply rewrap",
            "Preview is read-only. Applying rewrap is the deliberate write action after review.",
        )
        self.rewrap_status_label = QLabel("Select files and preview changes before applying.")
        self.rewrap_status_label.setWordWrap(True)
        self.rewrap_status_label.setStyleSheet(
            f"color:{COLORS.accent_text};font-size:12px;"
            f"background:{COLORS.chrome};border:1px solid {COLORS.border};"
            "border-radius:4px;padding:10px;"
        )
        review_stage.add_widget(self.rewrap_status_label)

        action_row = QHBoxLayout()
        action_row.setSpacing(Spacing.SM)
        self.rewrap_scan_btn = _make_btn("🔎  Preview rewrap", "#555")
        self.rewrap_scan_btn.setToolTip("Preview deterministic changes without writing files")
        self.rewrap_scan_btn.clicked.connect(lambda: self._run_rewrap(False))
        action_row.addWidget(self.rewrap_scan_btn)
        self.rewrap_apply_btn = _make_btn("✔  Apply rewrap", "#0e639c")
        self.rewrap_apply_btn.setToolTip(
            "Apply the selected widths and scope to the selected game data JSON"
        )
        self.rewrap_apply_btn.clicked.connect(lambda: self._run_rewrap(True))
        _equalize_action_buttons(
            self.rewrap_scan_btn,
            self.rewrap_apply_btn,
            width=Geometry.ACTION_WIDE,
        )
        action_row.addWidget(self.rewrap_apply_btn)
        action_row.setStretch(0, 1)
        action_row.setStretch(1, 1)
        action_row.addStretch()
        review_stage.add_layout(action_row)

        self.rewrap_results = QListWidget()
        self.rewrap_results.setMinimumHeight(180)
        self.rewrap_results.setWordWrap(True)
        self.rewrap_results.setTextElideMode(Qt.ElideNone)
        self.rewrap_results.setStyleSheet(
            f"QListWidget{{background:{COLORS.chrome};border:1px solid {COLORS.border};"
            f"border-radius:4px;color:{COLORS.text_secondary};font-size:11px;padding:4px;}}"
            f"QListWidget::item{{padding:6px;border-bottom:1px solid {COLORS.surface_1};}}"
        )
        results_host = QWidget()
        results_layout = QVBoxLayout(results_host)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.addWidget(self.rewrap_results)
        self._rewrap_results_disclosure = DisclosureSection(
            "Scan results", results_host, expanded=False
        )
        review_stage.add_widget(self._rewrap_results_disclosure)
        layout.addWidget(review_stage)

        # Stage 4 — final data QA. MV/MZ release packaging happens only after
        # images and playtesting; Ace exposes an engine-specific release action
        # here because its later MV/MZ-only steps are hidden.
        finish_stage = WorkflowStageCard(
            4,
            "Run final QA",
            "Audit the rewrapped game data before continuing to images and playtesting.",
        )
        self._rewrap_finish_stage = finish_stage
        self._qa_ai_help_banner = StatusBanner(
            "How to use this: click Copy final QA skill, paste the copied instructions into "
            "your AI helper with the translated game folder open, and fix the problems it "
            "finds before moving on.",
            "info",
        )
        finish_stage.add_widget(self._qa_ai_help_banner)
        finish_actions = QHBoxLayout()
        finish_actions.setSpacing(Spacing.SM)
        qa_btn = _make_btn("🔎  Copy final QA skill", "#8a6d3b")
        qa_btn.setToolTip(
            "After export and rewrap, copy the scalable QA skill for the detected game data folder."
        )
        qa_btn.clicked.connect(self._copy_translation_qa_prompt)
        _size_action_button(qa_btn, Geometry.ACTION_WIDE)
        finish_actions.addWidget(qa_btn)

        self._ace_release_zip_btn = _make_btn(
            "📦  Build public release ZIP", "#0e639c"
        )
        self._ace_release_zip_btn.setToolTip(
            "Archive the detected Ace game folder after rewrap and final QA. Excludes DazedTL "
            "workspaces, version-control files, documentation, backups, and saves; keeps "
            "GameUpdate files. The source game folder is not changed."
        )
        self._ace_release_zip_btn.clicked.connect(self._create_public_release)
        _size_action_button(self._ace_release_zip_btn, Geometry.ACTION_WIDE)
        self._ace_release_zip_btn.hide()
        finish_actions.addWidget(self._ace_release_zip_btn)
        _equalize_action_buttons(
            qa_btn,
            self._ace_release_zip_btn,
            width=Geometry.ACTION_WIDE,
        )
        finish_actions.addStretch()
        finish_stage.add_layout(finish_actions)
        layout.addWidget(finish_stage)

        QTimer.singleShot(0, self._refresh_rewrap_files)
        QTimer.singleShot(0, self._load_rewrap_widths)

    # ── Step 5: Plugins.js + Export ────────────────────────────────────────

    def _build_step5_finish(self, layout: QVBoxLayout):
        self._add_step_header(layout, "Step 5 — Export to Game", 5)

        preparation = WorkflowStageCard(
            1,
            "Prepare plugin or script translations",
            "Use the game-local Glossary with the engine-specific translation skill before editing player-visible strings.",
        )
        prep_layout = preparation.body
        self._step6_section_label = QLabel("Plugins")
        self._step6_section_label.setObjectName("workflowFieldCaption")
        self._step6_section_label.setStyleSheet(
            f"color:{COLORS.text_muted};font-size:11px;font-weight:600;"
        )
        prep_layout.addWidget(self._step6_section_label)

        self._plugin_ai_help_banner = StatusBanner(
            "How to use this: copy the translation skill, paste it into your AI helper with "
            "the game folder open, and review its "
            "plugin or script changes before moving on.",
            "info",
        )
        prep_layout.addWidget(self._plugin_ai_help_banner)

        self._step6_copy_btn = _make_btn("Copy plugin skill", "#555")
        self._step6_copy_btn.setToolTip(
            "Copy a prompt that audits plugins.js and enabled plugin sources, asks what "
            "needs translation, then edits approved player-visible strings in place."
        )
        self._step6_copy_btn.clicked.connect(self._copy_plugins_js_translate_prompt)
        _equalize_action_buttons(self._step6_copy_btn, width=Geometry.ACTION_WIDE)
        prep_actions = QHBoxLayout()
        prep_actions.setSpacing(Spacing.SM)
        prep_actions.addWidget(self._step6_copy_btn, 1)
        prep_actions.addStretch()
        prep_layout.addLayout(prep_actions)
        layout.addWidget(preparation)

        export_card = WorkflowStageCard(
            2,
            "Export reviewed translations",
            "Export the files selected in Step 0, or every translated JSON file in translated/.",
        )
        export_layout = export_card.body
        self._step6_export_destination = QLabel("Game data destination: detect a project in Step 0")
        self._step6_export_destination.setStyleSheet(
            f"color:{COLORS.accent_text};font-size:12px;font-family:Consolas,monospace;"
        )
        self._step6_export_destination.setTextInteractionFlags(Qt.TextSelectableByMouse)
        export_layout.addWidget(self._step6_export_destination)

        export_active_btn = _make_btn("📤  Export selected files", "#0e639c")
        export_active_btn.setToolTip(
            "Only export files whose names match those currently in files/\n"
            "(i.e. the files you imported for this project)"
        )
        export_active_btn.clicked.connect(self._export_active_files)

        export_all_btn = _make_btn("📤  Export all translated files", "#555")
        export_all_btn.setToolTip(
            "Export every file in translated/ regardless of what is in files/"
        )
        export_all_btn.clicked.connect(self._export_to_game)
        _equalize_action_buttons(
            export_active_btn,
            export_all_btn,
            width=Geometry.ACTION_WIDE,
        )
        export_actions = QHBoxLayout()
        export_actions.setSpacing(Spacing.SM)
        export_actions.addWidget(export_active_btn, 1)
        export_actions.addWidget(export_all_btn, 1)
        export_actions.addStretch()
        export_layout.addLayout(export_actions)
        layout.addWidget(export_card)

    # ── Step 7: Editable images ─────────────────────────────────────────────

    def _build_step6_images(self, layout: QVBoxLayout):
        self._add_step_header(layout, "Step 7 — Translate Images", 7)

        status_box = WorkflowStageCard(
            1,
            "Check image readiness",
            "Verify the game folder, encryption key, Glossary, and editable-image workspace.",
        )
        status_layout = status_box.body

        self._image_workflow_status = QLabel("Open this step to check image readiness.")
        self._image_workflow_status.setWordWrap(True)
        self._image_workflow_status.setTextFormat(Qt.RichText)
        self._image_workflow_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._image_workflow_status.setStyleSheet(
            "color:#c8c8c8;font-size:12px;line-height:1.4;"
        )
        status_layout.addWidget(self._image_workflow_status)

        refresh_btn = _make_btn("↻  Refresh readiness", "#555")
        refresh_btn.setToolTip("Recheck the game folder, images, encryption key, and Glossary")
        _size_action_button(refresh_btn)
        refresh_btn.clicked.connect(self._refresh_image_workflow_status)
        status_layout.addWidget(refresh_btn, 0, Qt.AlignLeft)
        layout.addWidget(status_box)

        flow_box = WorkflowStageCard(
            2,
            "Prepare images for translation",
            "Create editable PNG copies and run the image skill with your coding agent.",
        )
        flow_layout = flow_box.body

        flow_text = QLabel(
            "Open the Image Manager and decrypt source images into editable PNG copies. "
            "It will use the Glossary already copied to the game in Step 5. Then use "
            "<b>Copy skill</b> there and give the generated instructions to your coding agent."
        )
        flow_text.setWordWrap(True)
        flow_text.setTextFormat(Qt.RichText)
        flow_text.setStyleSheet("color:#c8c8c8;font-size:12px;")
        flow_layout.addWidget(flow_text)

        layout.addWidget(flow_box)

        patch_stage = WorkflowStageCard(
            3,
            "Review and patch translated images",
            "Approve translated PNGs, then patch selected or all approved images in the Image Manager.",
        )
        patch_actions = QHBoxLayout()
        patch_actions.setSpacing(Spacing.SM)
        self._open_images_btn = _make_btn("🖼  Open Image Manager", "#0e639c")
        self._open_images_btn.setToolTip(
            "Open the existing Image Manager using the Step 0 game folder."
        )
        self._open_images_btn.clicked.connect(self._open_image_manager)
        _size_action_button(self._open_images_btn, Geometry.ACTION_WIDE)
        patch_actions.addWidget(self._open_images_btn)
        patch_actions.addStretch()
        patch_stage.add_layout(patch_actions)
        layout.addWidget(patch_stage)
        _equalize_action_buttons(
            refresh_btn,
            self._open_images_btn,
            width=320,
            maximum=360,
        )

    # ── Step 8: Playtest (TL Inspector) ─────────────────────────────────────

    def _build_step8_playtest(self, layout: QVBoxLayout):
        self._step8_section_label = self._add_step_header(
            layout, "Step 8 — Playtest Tools", 8
        )

        settings_box = WorkflowStageCard(
            1,
            "Configure playtest tools",
            "Set overlay hotkeys, UI scale, and the editor opened by TL Inspector.",
        )
        settings_inner = settings_box.body

        _PT_LABEL_W = Geometry.FORM_LABEL
        _PT_FIELD_W = Geometry.FIELD_COMPACT
        _PT_BTN_W = 132
        _PT_LBL_STYLE = "color:#a6a6a6;font-size:12px;"
        _PT_SECTION_STYLE = "color:#f2f2f2;font-size:12px;font-weight:bold;"

        hotkey_title = QLabel("Hotkeys")
        hotkey_title.setStyleSheet(_PT_SECTION_STYLE)
        settings_inner.addWidget(hotkey_title)

        hotkey_row = QHBoxLayout()
        hotkey_row.setSpacing(Spacing.SM)

        insp_lbl = QLabel("Inspector hotkey:")
        insp_lbl.setMinimumWidth(_PT_LABEL_W)
        insp_lbl.setWordWrap(True)
        insp_lbl.setStyleSheet(_PT_LBL_STYLE)
        insp_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hotkey_row.addWidget(insp_lbl)

        self._pt_hotkey_edit = QLineEdit("F9")
        self._pt_hotkey_edit.setFixedWidth(_PT_FIELD_W)
        self._pt_hotkey_edit.setPlaceholderText("F9")
        hotkey_row.addWidget(self._pt_hotkey_edit)

        hotkey_row.addSpacing(16)

        self._pt_forge_hotkey_lbl = QLabel("Forge hotkey:")
        self._pt_forge_hotkey_lbl.setMinimumWidth(_PT_LABEL_W)
        self._pt_forge_hotkey_lbl.setWordWrap(True)
        self._pt_forge_hotkey_lbl.setStyleSheet(_PT_LBL_STYLE)
        self._pt_forge_hotkey_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hotkey_row.addWidget(self._pt_forge_hotkey_lbl)

        self._pt_forge_hotkey_edit = QLineEdit("F10")
        self._pt_forge_hotkey_edit.setFixedWidth(_PT_FIELD_W)
        self._pt_forge_hotkey_edit.setPlaceholderText("F8")
        self._pt_forge_hotkey_edit.setToolTip(
            "Key to open Forge (e.g. F8, F6, F10).\n"
            "MV uses the legacy plugin; MZ uses the modern one.\n"
            "Under Wine/Linux, F10 is often stolen by the window menu - prefer F8.\n"
            "Click Apply settings to game after changing."
        )
        hotkey_row.addWidget(self._pt_forge_hotkey_edit)

        hotkey_row.addStretch(1)
        settings_inner.addLayout(hotkey_row)

        scale_row = QHBoxLayout()
        scale_row.setSpacing(Spacing.SM)
        scale_lbl = QLabel("Overlay scale:")
        scale_lbl.setMinimumWidth(_PT_LABEL_W)
        scale_lbl.setStyleSheet(_PT_LBL_STYLE)
        scale_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        scale_row.addWidget(scale_lbl)

        self._pt_ui_scale_combo = QComboBox()
        self._pt_ui_scale_combo.setToolTip(
            "In-game overlay size. Auto scales from window size and display DPI."
        )
        for label, value in (
            ("Auto (match game width)", "auto"),
            ("100%", "1"),
            ("125%", "1.25"),
            ("150%", "1.5"),
            ("175%", "1.75"),
            ("200%", "2"),
            ("225%", "2.25"),
            ("250%", "2.5"),
        ):
            self._pt_ui_scale_combo.addItem(label, value)
        scale_row.addWidget(self._pt_ui_scale_combo, 1)
        settings_inner.addLayout(scale_row)

        editor_title = QLabel("Source editor")
        editor_title.setStyleSheet(_PT_SECTION_STYLE + "padding-top:2px;")
        settings_inner.addWidget(editor_title)

        editor_grid = QGridLayout()
        editor_grid.setHorizontalSpacing(8)
        editor_grid.setVerticalSpacing(6)
        editor_grid.setColumnMinimumWidth(0, _PT_LABEL_W)
        editor_grid.setColumnStretch(1, 1)

        editor_lbl = QLabel("Open files with:")
        editor_lbl.setStyleSheet(_PT_LBL_STYLE)
        editor_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        editor_grid.addWidget(editor_lbl, 0, 0)

        self._tli_editor_combo = QComboBox()
        self._tli_editor_combo.currentIndexChanged.connect(self._on_tli_editor_combo_changed)
        editor_grid.addWidget(self._tli_editor_combo, 0, 1)

        detect_btn = _make_btn("Find editors", "#4a4a4a")
        detect_btn.setMinimumWidth(_PT_BTN_W)
        detect_btn.setToolTip("Scan this PC for VS Code, Insiders, or Cursor")
        detect_btn.clicked.connect(self._detect_tli_editors)
        editor_grid.addWidget(detect_btn, 0, 2)

        custom_lbl = QLabel("Editor path:")
        custom_lbl.setStyleSheet(_PT_LBL_STYLE)
        custom_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        editor_grid.addWidget(custom_lbl, 1, 0)

        self._tli_editor_custom = QLineEdit()
        self._tli_editor_custom.setPlaceholderText("Custom editor executable…")
        self._tli_editor_custom.setEnabled(False)
        editor_grid.addWidget(self._tli_editor_custom, 1, 1)

        browse_editor_btn = _make_btn("Choose…", "#4a4a4a")
        browse_editor_btn.setToolTip("Choose a custom editor executable")
        browse_editor_btn.setMinimumWidth(_PT_BTN_W)
        browse_editor_btn.clicked.connect(self._browse_tli_editor)
        editor_grid.addWidget(browse_editor_btn, 1, 2)
        equalize_button_widths(
            (detect_btn, browse_editor_btn),
            minimum=_PT_BTN_W,
            maximum=_PT_BTN_W,
        )

        self._tli_detect_label = QLabel("")
        self._tli_detect_label.setWordWrap(True)
        self._tli_detect_label.setStyleSheet("color:#77777a;font-size:11px;")
        editor_grid.addWidget(self._tli_detect_label, 2, 1, 1, 2)

        settings_inner.addLayout(editor_grid)

        action_row = QHBoxLayout()
        action_row.setSpacing(Spacing.SM)
        save_pt_btn = _make_btn("✔  Save defaults", "#0e639c")
        save_pt_btn.setMinimumHeight(Geometry.CONTROL_COMPACT)
        save_pt_btn.setToolTip("Save hotkeys, scale, and editor defaults to .env")
        save_pt_btn.clicked.connect(self._save_playtest_settings)
        action_row.addWidget(save_pt_btn)

        apply_pt_btn = _make_btn("↻  Apply settings to game", "#0e639c")
        apply_pt_btn.setMinimumHeight(Geometry.CONTROL_COMPACT)
        apply_pt_btn.setToolTip("Update installed playtest plugins with the current settings")
        apply_pt_btn.clicked.connect(self._apply_playtest_settings)
        _equalize_action_buttons(
            save_pt_btn,
            apply_pt_btn,
            width=Geometry.ACTION_WIDE,
        )
        action_row.addWidget(apply_pt_btn)
        action_row.setStretch(0, 1)
        action_row.setStretch(1, 1)
        action_row.addStretch()

        settings_inner.addLayout(action_row)
        layout.addWidget(settings_box)
        self._step8_settings_box = settings_box

        # ── Plugins (TL Inspector + Forge) ────────────────────────────────────
        plugins_box = WorkflowStageCard(
            2,
            "Install playtest plugins",
            "TL Inspector opens source context from the game; Forge provides the in-game editing overlay for MV/MZ.",
        )
        plugins_inner = plugins_box.body

        _PT_SECTION_STYLE = "color:#f2f2f2;font-size:12px;font-weight:bold;"

        tli_title = QLabel("TL Inspector")
        tli_title.setStyleSheet(_PT_SECTION_STYLE)
        plugins_inner.addWidget(tli_title)

        self._tli_status_label = QLabel("Status: select a project in Step 0.")
        self._tli_status_label.setWordWrap(True)
        self._tli_status_label.setStyleSheet("color:#77777a;font-size:13px;")
        plugins_inner.addWidget(self._tli_status_label)

        tli_btn_row = QHBoxLayout()
        tli_btn_row.setSpacing(Spacing.SM)
        self._tli_install_btn = _make_btn("⬇  Install TL Inspector", "#0e639c")
        self._tli_install_btn.setMinimumHeight(30)
        self._tli_install_btn.setToolTip("Install or update TL Inspector in the selected game")
        self._tli_install_btn.clicked.connect(self._install_tl_inspector)
        tli_btn_row.addWidget(self._tli_install_btn)

        self._tli_uninstall_btn = _make_btn("⬆  Remove TL Inspector", "#7a3a3a")
        self._tli_uninstall_btn.setToolTip("Remove TL Inspector from the selected game")
        self._tli_uninstall_btn.setMinimumHeight(30)
        self._tli_uninstall_btn.clicked.connect(self._uninstall_tl_inspector)
        _equalize_action_buttons(
            self._tli_install_btn,
            self._tli_uninstall_btn,
            width=Geometry.ACTION_WIDE,
        )
        tli_btn_row.addWidget(self._tli_uninstall_btn)
        tli_btn_row.setStretch(0, 1)
        tli_btn_row.setStretch(1, 1)
        tli_btn_row.addStretch()
        plugins_inner.addLayout(tli_btn_row)

        self._step8_forge_section = QWidget()
        self._step8_forge_section.setStyleSheet("background:transparent;")
        forge_section_layout = QVBoxLayout(self._step8_forge_section)
        forge_section_layout.setContentsMargins(0, 4, 0, 0)
        forge_section_layout.setSpacing(Spacing.SM)

        forge_title = QLabel("Forge (MV / MZ)")
        forge_title.setStyleSheet(_PT_SECTION_STYLE)
        forge_section_layout.addWidget(forge_title)

        self._forge_status_label = QLabel("Status: requires an MV or MZ project.")
        self._forge_status_label.setWordWrap(True)
        self._forge_status_label.setStyleSheet("color:#77777a;font-size:13px;")
        forge_section_layout.addWidget(self._forge_status_label)

        forge_btn_row = QHBoxLayout()
        forge_btn_row.setSpacing(Spacing.SM)
        self._forge_install_btn = _make_btn("⬇  Install Forge", "#0e639c")
        self._forge_install_btn.setMinimumHeight(30)
        self._forge_install_btn.setToolTip("Install or update Forge in the selected game")
        self._forge_install_btn.clicked.connect(self._install_forge)
        forge_btn_row.addWidget(self._forge_install_btn)

        self._forge_uninstall_btn = _make_btn("⬆  Remove Forge", "#7a3a3a")
        self._forge_uninstall_btn.setToolTip("Remove Forge from the selected game")
        self._forge_uninstall_btn.setMinimumHeight(30)
        self._forge_uninstall_btn.clicked.connect(self._uninstall_forge)
        _equalize_action_buttons(
            self._forge_install_btn,
            self._forge_uninstall_btn,
            width=Geometry.ACTION_WIDE,
        )
        forge_btn_row.addWidget(self._forge_uninstall_btn)
        forge_btn_row.setStretch(0, 1)
        forge_btn_row.setStretch(1, 1)
        forge_btn_row.addStretch()
        forge_section_layout.addLayout(forge_btn_row)

        plugins_inner.addWidget(self._step8_forge_section)

        self._step8_tli_credits = QLabel("Idea by Sakura · Plugin by Kao_SSS")
        self._step8_tli_credits.setStyleSheet("color:#77777a;font-size:11px;font-style:italic;padding-top:2px;")
        plugins_inner.addWidget(self._step8_tli_credits)

        self._step8_forge_credits = QLabel(
            'Forge by <a href="https://gitgud.io/zero64801/forge-mvmz" style="color:#7a9abf">len</a>'
        )
        self._step8_forge_credits.setStyleSheet("color:#77777a;font-size:11px;font-style:italic;")
        self._step8_forge_credits.setTextFormat(Qt.RichText)
        self._step8_forge_credits.setOpenExternalLinks(True)
        plugins_inner.addWidget(self._step8_forge_credits)

        self._install_both_btn = _make_btn("⬇  Install both plugins", "#0e639c")
        self._install_both_btn.setMinimumHeight(30)
        self._install_both_btn.setToolTip(
            "Install or update TL Inspector and Forge in the selected MV/MZ game"
        )
        self._install_both_btn.clicked.connect(self._install_both_playtest)
        equalize_button_widths(
            (
                self._tli_install_btn,
                self._tli_uninstall_btn,
                self._forge_install_btn,
                self._forge_uninstall_btn,
                self._install_both_btn,
            ),
            minimum=Geometry.ACTION_WIDE,
            maximum=Geometry.ACTION_WIDE,
        )
        plugins_inner.addWidget(self._install_both_btn)

        layout.addWidget(plugins_box)
        self._step8_playtest_box = plugins_box
        self._step8_forge_box = self._step8_forge_section

        verify_stage = WorkflowStageCard(
            3,
            "Verify plugins in game",
            "Launch the game, press the configured hotkeys, and confirm that each installed overlay opens correctly.",
        )
        verify_row = QHBoxLayout()
        verify_row.setSpacing(Spacing.SM)
        verify_hint = QLabel(
            "If a tool does not open, check its status above and try a different hotkey before reinstalling."
        )
        verify_hint.setWordWrap(True)
        verify_hint.setStyleSheet(f"color:{COLORS.text_muted};font-size:12px;")
        verify_row.addWidget(verify_hint, 1)
        refresh_playtest_btn = _make_btn("↻  Refresh plugin status", "#555")
        _size_action_button(refresh_playtest_btn)
        refresh_playtest_btn.clicked.connect(self._refresh_playtest_status)
        verify_row.addWidget(refresh_playtest_btn)
        verify_stage.add_layout(verify_row)
        layout.addWidget(verify_stage)

        release_stage = WorkflowStageCard(
            4,
            "Build the public release",
            "After translated images are patched and the game has been fully playtested, create the ZIP you can share.",
        )
        release_hint = StatusBanner(
            "This is the last workflow action. The ZIP leaves the game folder unchanged and "
            "omits translation workspaces, version-control files, backups, and saves.",
            "info",
        )
        release_stage.add_widget(release_hint)
        release_row = QHBoxLayout()
        release_row.setSpacing(Spacing.SM)
        self._release_zip_btn = _make_btn(
            "📦  Build public release ZIP", "#0e639c"
        )
        self._release_zip_btn.setToolTip(
            "Archive the fully reviewed game folder after images and playtesting. Excludes "
            "DazedTL workspaces, version-control files, documentation, backups, and saves; "
            "keeps GameUpdate files and installed plugins. The game folder is not changed."
        )
        self._release_zip_btn.clicked.connect(self._create_public_release)
        _size_action_button(self._release_zip_btn, Geometry.ACTION_WIDE)
        release_row.addWidget(self._release_zip_btn)
        release_row.addStretch()
        release_stage.add_layout(release_row)
        layout.addWidget(release_stage)

        self._populate_tli_editor_combo()
        self._load_playtest_settings()

    def _refresh_image_workflow_status(self):
        """Check that Step 0 points at an MV/MZ root ready for image work."""
        label = getattr(self, "_image_workflow_status", None)
        button = getattr(self, "_open_images_btn", None)
        if label is None:
            return
        if self._ace_encrypted or self._ace_rvdata_dir or self._ace_json_dir:
            label.setText(
                "<span style='color:#f2c94c'>⚠ This guided image step is configured for RPG "
                "Maker MV/MZ. The standalone Images page also supports Generic loose PNGs, "
                "but no Ace archive profile is available yet.</span>"
            )
            if button is not None:
                button.setEnabled(False)
            return

        game_root = self.folder_edit.text().strip()
        if not game_root:
            label.setText(
                "<span style='color:#f2c94c'>⚠ Complete Step 0 and select the actual game "
                "root first.</span>"
            )
            if button is not None:
                button.setEnabled(False)
            return

        import html

        report = _inspect_image_workflow(game_root)
        if not report["ok"]:
            label.setText(
                "<span style='color:#f48771'>✗ The Step 0 folder is not ready for image "
                f"management: {html.escape(report['error'])}</span><br>"
                "Select the folder that directly contains <code>img/</code>, or contains "
                "<code>www/img/</code>."
            )
            if button is not None:
                button.setEnabled(False)
            return

        root = html.escape(str(report["root"]))
        editable_root = html.escape(str(report["editable_root"]))
        vocab = html.escape(str(report["vocab"]))
        lines = [
            f"<span style='color:#73c991'>✓ Project root:</span> <code>{root}</code>",
            f"<span style='color:#73c991'>✓ Runtime images:</span> "
            f"{report['runtime']:,} ({report['encrypted']:,} encrypted)",
        ]
        if report["key_ok"] is False:
            lines.append(
                "<span style='color:#f48771'>✗ Encryption key:</span> missing or invalid in "
                "<code>System.json</code>; encrypted images cannot be decrypted."
            )
        elif report["key_ok"] is True:
            lines.append("<span style='color:#73c991'>✓ Encryption key:</span> ready")
        else:
            lines.append("<span style='color:#73c991'>✓ Encryption key:</span> not required")

        if Path(report["vocab"]).is_file():
            lines.append(
                f"<span style='color:#73c991'>✓ Glossary:</span> <code>{vocab}</code>"
            )
        else:
            lines.append(
                "<span style='color:#f2c94c'>⚠ Glossary:</span> "
                f"<code>{vocab}</code> is missing. Copy it before using the AI skill."
            )

        if report["editable"]:
            lines.append(
                f"<span style='color:#73c991'>✓ Editable PNGs:</span> "
                f"{report['editable']:,} under <code>{editable_root}</code>"
            )
        else:
            lines.append(
                "<span style='color:#a6a6a6'>• Editable PNGs:</span> none yet. Open the Image Manager "
                "and make the images you want to translate editable."
            )

        if report["misplaced"]:
            lines.append(
                f"<span style='color:#f2c94c'>⚠ Workspace layout:</span> "
                f"{report['misplaced']:,} PNG(s) are outside <code>{editable_root}</code> and "
                "will not appear in the Image Manager."
            )
        else:
            lines.append(
                "<span style='color:#73c991'>✓ Workspace layout:</span> editable PNGs use "
                "the expected game-relative hierarchy."
            )
        label.setText("<br>".join(lines))
        if button is not None:
            button.setEnabled(True)

    def _open_image_manager(self):
        """Open the Images page with the current Step 0 project root."""
        game_root = self.folder_edit.text().strip()
        report = _inspect_image_workflow(game_root) if game_root else {"ok": False}
        if not report.get("ok"):
            QMessageBox.warning(
                self,
                "Images Setup",
                "Select a valid RPG Maker MV/MZ game root in Step 0 first.",
            )
            return
        self._save_setting("last_game_folder", str(report["root"]))
        parent = self.parent_window
        if hasattr(parent, "switch_page"):
            parent.switch_page(getattr(parent, "PAGE_IMAGES", 2))
            return
        self._log("⚠  Could not open the Images page from this window.")

    def _populate_tli_editor_combo(self, select: str | None = None):
        """Fill editor dropdown with auto-detect, found editors, and custom."""
        from util.tl_inspector.config import detect_editors

        combo = self._tli_editor_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Auto-detect (recommended)", "auto")
        for label, path in detect_editors():
            combo.addItem(f"{label} — {path}", str(path))
        combo.addItem("Custom path…", "__custom__")

        want = select
        if want is None:
            try:
                from util.tl_inspector.config import load_config
                want = load_config().get("editorCmd", "auto")
            except Exception:
                want = "auto"

        idx = combo.findData(want) if want else 0
        if idx >= 0:
            combo.setCurrentIndex(idx)
        elif want and want != "auto":
            custom_idx = combo.findData("__custom__")
            combo.setCurrentIndex(custom_idx if custom_idx >= 0 else 0)
            self._tli_editor_custom.setText(want)
        else:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)
        self._on_tli_editor_combo_changed()
        self._update_tli_detect_label()

    def _update_tli_detect_label(self):
        from util.tl_inspector.config import detect_editors, detect_primary_editor

        found = detect_editors()
        primary = detect_primary_editor()
        if primary:
            extra = f" ({len(found)} found)" if len(found) > 1 else ""
            self._tli_detect_label.setText(f"Detected on this PC: {primary}{extra}")
        else:
            self._tli_detect_label.setText(
                "No VS Code / Cursor found — install one or choose Custom path."
            )

    def _load_playtest_settings(self):
        """Load playtest hotkeys and editor settings from .env into Step 8 controls."""
        try:
            from util.playtest.config import load_config
            cfg = load_config()
        except Exception:
            cfg = {
                "hotkey": "F9",
                "forgeHotkey": "F10",
                "uiScale": "auto",
                "editorCmd": "auto",
            }

        self._pt_hotkey_edit.setText(cfg.get("hotkey", "F9"))
        self._pt_forge_hotkey_edit.setText(cfg.get("forgeHotkey", "F10"))
        want_scale = str(cfg.get("uiScale", "auto"))
        scale_idx = self._pt_ui_scale_combo.findData(want_scale)
        if scale_idx >= 0:
            self._pt_ui_scale_combo.setCurrentIndex(scale_idx)
        else:
            custom_idx = self._pt_ui_scale_combo.findData("auto")
            self._pt_ui_scale_combo.setCurrentIndex(custom_idx if custom_idx >= 0 else 0)
        self._populate_tli_editor_combo(select=cfg.get("editorCmd", "auto"))

    def _resolve_playtest_config(self) -> dict:
        """Build playtest config dict from Step 8 controls."""
        mode = self._tli_editor_combo.currentData()
        if mode == "__custom__":
            editor = self._tli_editor_custom.text().strip() or "auto"
        elif mode:
            editor = str(mode)
        else:
            editor = "auto"

        return {
            "hotkey": self._pt_hotkey_edit.text().strip() or "F9",
            "forgeHotkey": self._pt_forge_hotkey_edit.text().strip() or "F10",
            "uiScale": str(self._pt_ui_scale_combo.currentData() or "auto"),
            "editorCmd": editor,
            "workspaceFolder": "auto",
        }

    def _save_playtest_settings(self):
        cfg = self._resolve_playtest_config()
        try:
            from util.playtest.config import save_config
            save_config(cfg)
            self._log(
                "✅ Playtest settings saved — "
                f"inspector={cfg['hotkey']}, forge={cfg['forgeHotkey']}, "
                f"scale={cfg['uiScale']}, editor={cfg['editorCmd']}"
            )
        except Exception as exc:
            self._log(f"❌ Could not save playtest settings: {exc}")

    def _apply_playtest_settings(self):
        game_root = self.folder_edit.text().strip()
        if not game_root:
            self._log("⚠  No game folder set. Complete Step 0 first.")
            return
        cfg = self._resolve_playtest_config()
        try:
            from util.forge.installer import detect_engine
            from util.playtest.config import save_config

            save_config(cfg)
            info = detect_engine(Path(game_root))
            msgs: list[str] = []
            if info is not None:
                from util.forge.installer import apply_config as apply_forge
                from util.forge.installer import status as forge_status
                if forge_status(Path(game_root)).get("plugin_file"):
                    ok, msg = apply_forge(Path(game_root), cfg)
                    msgs.append(("✅ " if ok else "❌ ") + msg)
            from util.tl_inspector.installer import apply_config as apply_tli
            from util.tl_inspector.installer import status as tli_status
            if tli_status(Path(game_root)).get("plugin_file"):
                ok, msg = apply_tli(Path(game_root), cfg)
                msgs.append(("✅ " if ok else "❌ ") + msg)
            if not msgs:
                self._log("⚠  No playtest plugins installed in this game folder.")
                return
            for line in msgs:
                self._log(line)
        except Exception as exc:
            self._log(f"❌ Could not apply playtest settings: {exc}")
            return
        self._refresh_playtest_status()

    def _refresh_playtest_status(self):
        """Update Step 8 status labels for the current engine."""
        if getattr(self, "_step8_playtest_box", None) is not None:
            self._refresh_tl_inspector_status()
        self._refresh_forge_status()

    def _on_tli_editor_combo_changed(self, _index: int | None = None):
        custom = self._tli_editor_combo.currentData() == "__custom__"
        self._tli_editor_custom.setEnabled(custom)

    def _detect_tli_editors(self):
        try:
            from util.tl_inspector.config import load_config
            current = load_config().get("editorCmd", "auto")
        except Exception:
            current = "auto"
        self._populate_tli_editor_combo(select=current)
        self._log("🔍 Scanned for VS Code / Cursor installations.")

    def _browse_tli_editor(self):
        start = self._tli_editor_custom.text() or self._setting("last_tli_editor", "")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Editor Executable",
            start,
            "Executables (*.exe);;All Files (*)",
        )
        if not path:
            return
        self._save_setting("last_tli_editor", path)
        custom_idx = self._tli_editor_combo.findData("__custom__")
        if custom_idx >= 0:
            self._tli_editor_combo.setCurrentIndex(custom_idx)
        self._tli_editor_custom.setText(path)

    def _save_tli_editor_settings(self):
        self._save_playtest_settings()

    def _apply_tli_editor_settings(self):
        self._apply_playtest_settings()

    def _refresh_tl_inspector_status(self):
        """Update Step 8 TL Inspector status label from the current game folder."""
        label = getattr(self, "_tli_status_label", None)
        if label is None:
            return
        game_root = self.folder_edit.text().strip()
        if not game_root:
            label.setText("Status: no game folder set — complete Step 0 first.")
            label.setStyleSheet("color:#77777a;font-size:13px;")
            return
        try:
            from util.tl_inspector.installer import status
            st = status(Path(game_root))
        except Exception as exc:
            label.setText(f"Status: error — {exc}")
            label.setStyleSheet("color:#f48771;font-size:13px;")
            return

        if not st.get("ok"):
            label.setText(f"Status: {st.get('message', 'unsupported')}")
            label.setStyleSheet("color:#f2c94c;font-size:13px;")
            return

        engine = st.get("engine", "?")
        msg = st.get("message", "")
        parts = [f"RPG Maker {engine}", msg]
        if st.get("declared") and st.get("plugin_file"):
            detail = "plugin declared in plugins.js and file present"
        elif st.get("declared"):
            detail = "declared in plugins.js (plugin file missing)"
        elif st.get("plugin_file"):
            detail = "plugin file present (not declared in plugins.js)"
        else:
            detail = "not installed"
        label.setText(f"Status: {' · '.join(parts)} — {detail}")
        color = "#73c991" if st.get("declared") and st.get("plugin_file") else "#a6a6a6"
        label.setStyleSheet(f"color:{color};font-size:13px;")

    def _install_tl_inspector(self):
        game_root = self.folder_edit.text().strip()
        if not game_root:
            self._log("⚠  No game folder set. Complete Step 0 first.")
            return
        cfg = self._resolve_playtest_config()
        try:
            from util.playtest.config import save_config
            from util.tl_inspector.installer import install
            save_config(cfg)
            ok, msg = install(Path(game_root), cfg=cfg)
        except Exception as exc:
            self._log(f"❌ TL Inspector install failed: {exc}")
            return
        self._log(("✅ " if ok else "❌ ") + msg)
        self._refresh_playtest_status()

    def _uninstall_tl_inspector(self):
        game_root = self.folder_edit.text().strip()
        if not game_root:
            self._log("⚠  No game folder set. Complete Step 0 first.")
            return
        reply = QMessageBox.question(
            self,
            "Remove TL Inspector",
            "Remove TLInspector from plugins.js and delete the plugin file?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            from util.tl_inspector.installer import uninstall
            ok, msg = uninstall(Path(game_root))
        except Exception as exc:
            self._log(f"❌ TL Inspector uninstall failed: {exc}")
            return
        self._log(("✅ " if ok else "❌ ") + msg)
        self._refresh_playtest_status()

    def _refresh_forge_status(self):
        """Update Step 8 Forge status label from the current game folder."""
        label = getattr(self, "_forge_status_label", None)
        if label is None:
            return
        game_root = self.folder_edit.text().strip()
        if not game_root:
            label.setText("Status: no game folder set — complete Step 0 first.")
            label.setStyleSheet("color:#77777a;font-size:13px;")
            return
        try:
            from util.forge.installer import detect_engine, status
            if detect_engine(Path(game_root)) is None:
                label.setText("Status: not an MV/MZ project.")
                label.setStyleSheet("color:#f2c94c;font-size:13px;")
                return
            st = status(Path(game_root))
        except Exception as exc:
            label.setText(f"Status: error — {exc}")
            label.setStyleSheet("color:#f48771;font-size:13px;")
            return

        engine = st.get("engine", "?")
        msg = st.get("message", "")
        if st.get("declared") and st.get("plugin_file"):
            detail = "plugin declared in plugins.js and file present"
        elif st.get("declared"):
            detail = "declared in plugins.js (plugin file missing)"
        elif st.get("plugin_file"):
            detail = "plugin file present (not declared in plugins.js)"
        else:
            detail = "not installed"
        label.setText(f"Status: RPG Maker {engine} · {msg} — {detail}")
        color = "#73c991" if st.get("declared") and st.get("plugin_file") else "#a6a6a6"
        label.setStyleSheet(f"color:{color};font-size:13px;")

    def _install_forge(self):
        game_root = self.folder_edit.text().strip()
        if not game_root:
            self._log("⚠  No game folder set. Complete Step 0 first.")
            return
        cfg = self._resolve_playtest_config()
        try:
            from util.playtest.config import save_config
            from util.forge.installer import install
            save_config(cfg)
            ok, msg = install(Path(game_root), cfg=cfg)
        except Exception as exc:
            self._log(f"❌ Forge install failed: {exc}")
            return
        self._log(("✅ " if ok else "❌ ") + msg)
        self._refresh_playtest_status()

    def _install_both_playtest(self):
        game_root = self.folder_edit.text().strip()
        if not game_root:
            self._log("⚠  No game folder set. Complete Step 0 first.")
            return
        try:
            from util.forge.installer import detect_engine
            if detect_engine(Path(game_root)) is None:
                self._log("⚠  Installing both plugins requires an MV or MZ project.")
                return
        except Exception as exc:
            self._log(f"❌ Could not detect engine: {exc}")
            return

        cfg = self._resolve_playtest_config()
        try:
            from util.playtest.config import save_config
            from util.tl_inspector.installer import install as install_tli
            from util.forge.installer import install as install_forge

            save_config(cfg)
            ok_tli, msg_tli = install_tli(Path(game_root), cfg=cfg)
            self._log(("✅ " if ok_tli else "❌ ") + msg_tli)
            if not ok_tli:
                return
            ok_forge, msg_forge = install_forge(Path(game_root), cfg=cfg)
            self._log(("✅ " if ok_forge else "❌ ") + msg_forge)
        except Exception as exc:
            self._log(f"❌ Installing both plugins failed: {exc}")
            return
        self._refresh_playtest_status()

    def _uninstall_forge(self):
        game_root = self.folder_edit.text().strip()
        if not game_root:
            self._log("⚠  No game folder set. Complete Step 0 first.")
            return
        reply = QMessageBox.question(
            self,
            "Remove Forge",
            "Remove Forge from plugins.js and delete the plugin file?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            from util.forge.installer import uninstall
            ok, msg = uninstall(Path(game_root))
        except Exception as exc:
            self._log(f"❌ Forge uninstall failed: {exc}")
            return
        self._log(("✅ " if ok else "❌ ") + msg)
        self._refresh_playtest_status()

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
        """Adapt plugins/scripts controls for MV/MZ vs Ace; hide Playtest on Ace."""
        # Step 1 prettier / plugins.js format - only relevant for MV/MZ
        for attr in ("_pp_dazedformat_title", "_pp_dazedformat_box",
                     "_pp_plugins_js_title", "_pp_plugins_js_box"):
            w = getattr(self, attr, None)
            if w is not None:
                w.setVisible(not is_ace)
        # Step 5 plugins subsection title + prompt tooltip
        lbl = getattr(self, "_step6_section_label", None)
        if lbl is not None:
            lbl.setText("Scripts" if is_ace else "Plugins")
        btn = getattr(self, "_step6_copy_btn", None)
        if btn is not None:
            if is_ace:
                btn.setText("Copy Ruby translation skill")
                btn.setToolTip(
                    "Copy a prompt that instructs Copilot/Cursor to translate only "
                    "visible player-facing strings in the Ace .rb script files. "
                    "It audits first, asks what to translate, then edits approved files in place."
                )
            else:
                btn.setText("Copy plugin skill")
                btn.setToolTip(
                    "Copy a prompt that audits plugins.js and enabled plugin sources, asks what "
                    "needs translation, then edits approved player-visible strings in place."
                )
        destination = getattr(self, "_step6_export_destination", None)
        if destination is not None:
            destination.setText(
                f"Game data destination: {self._data_path}"
                if self._data_path else
                "Game data destination: detect a project in Step 0"
            )
        # Steps 7–8 in this RPG workflow are MV/MZ only. The standalone Images
        # page also supports Generic loose PNG projects.
        show_mvmz_tools = not is_ace
        tool_indices = (7, 8)
        for tool_idx in tool_indices:
            if hasattr(self, "_step_tabs") and self._step_tabs.count() > tool_idx:
                if hasattr(self._step_tabs, "setTabVisible"):
                    self._step_tabs.setTabVisible(tool_idx, show_mvmz_tools)
                else:
                    self._step_tabs.setTabEnabled(tool_idx, show_mvmz_tools)
            if hasattr(self, "_step_buttons") and len(self._step_buttons) > tool_idx:
                self._step_buttons[tool_idx].setVisible(show_mvmz_tools)
                self._step_buttons[tool_idx].setEnabled(show_mvmz_tools)
        ace_release_btn = getattr(self, "_ace_release_zip_btn", None)
        if ace_release_btn is not None:
            ace_release_btn.setVisible(is_ace)
        finish_stage = getattr(self, "_rewrap_finish_stage", None)
        if finish_stage is not None:
            finish_stage.title_label.setText(
                "Run final QA and build the release" if is_ace else "Run final QA"
            )
            finish_stage.description_label.setText(
                "Audit the rewrapped game data, then build the Ace release."
                if is_ace else
                "Audit the rewrapped game data before continuing to images and playtesting."
            )
        if is_ace and self._step_tabs.currentIndex() in tool_indices:
            self._goto_step(6)
        self._refresh_step_strip()
        box = getattr(self, "_step8_playtest_box", None)
        install_both_btn = getattr(self, "_install_both_btn", None)
        if box is not None:
            box.setVisible(show_mvmz_tools)
            box.setEnabled(show_mvmz_tools)
        if install_both_btn is not None:
            install_both_btn.setVisible(show_mvmz_tools)
        if show_mvmz_tools:
            self._refresh_playtest_status()

    def _detect_folder(self):
        folder = self.folder_edit.text().strip()
        if not folder:
            self._log("⚠  No folder path entered.")
            return

        self._save_setting("last_game_folder", folder)
        if hasattr(self, "setup_editors"):
            self.setup_editors.reload_all()
        self.detected_label.setText("Scanning…")
        self.detected_label.setStyleSheet(
            "color:#a6a6a6;font-size:13px;padding:4px 8px;"
            "background-color:#252526;border:1px solid #45454a;"
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
                "color:#f2c94c;font-size:13px;padding:4px 8px;"
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
                "color:#f2c94c;font-size:13px;padding:4px 8px;"
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
                    "color:#73c991;font-size:13px;padding:4px 8px;"
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
                    "color:#a6a6a6;font-size:13px;padding:4px 8px;"
                    "background-color:#252526;border:1px solid #45454a;"
                    "border-radius:4px;margin:4px 0;"
                )
                self._run_rv2json_create()
            return  # scan continues above or in _on_rv2json_create_done
        # ─────────────────────────────────────────────────────────────────────

        self.detected_label.setText(
            f"Engine: {engine}   ·   Data folder: {data_path}"
        )
        self.detected_label.setStyleSheet(
            "color:#73c991;font-size:13px;padding:4px 8px;"
            "background-color:#1f2b1f;border:1px solid #2a4a2a;"
            "border-radius:4px;margin:4px 0;"
        )
        self._log(f"Detected data folder: {data_path}  (engine: {engine})")
        self._update_step6_for_engine(False)

        worker = _ScanWorker(self._data_path, self._engine)
        worker.done.connect(self._on_scan_done)
        worker.error.connect(lambda e: self._log(f"❌ Scan error: {e}"))
        self._worker = worker
        worker.start()

    def _on_scan_done(self, items: list):
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
                lw.setForeground(__import__("PyQt5.QtGui", fromlist=["QColor"]).QColor("#75beff"))
            elif cat == "map":
                lw.setForeground(__import__("PyQt5.QtGui", fromlist=["QColor"]).QColor("#c8c8c8"))
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

    _BASE_SEPARATOR = _SHARED_BASE_SEPARATOR

    def _copy_project_setup_prompt(self):
        """Copy the Project Setup skill, optionally prepending known speakers."""
        try:
            speakers = self._read_vocab_speakers()
            prepend = ""
            if speakers:
                speaker_lines = "\n".join(f"  {orig} ({tl})" for orig, tl in speakers)
                prepend = (
                    "<known_speakers>\n"
                    "These character names were extracted from the game files by the Parse Speakers tool.\n"
                    "For the glossary block '# Game Characters', prefer entries for these names, "
                    "then cross-check Actors.json for other major named actors.\n"
                    "\n"
                    + speaker_lines
                    + "\n</known_speakers>\n"
                )
            prompt = load_project_setup("rpgmaker", prepend=prepend)
            self._copy_to_clipboard(prompt, "Project Setup skill copied.")
        except Exception as exc:
            self._log(f"❌ Could not load Project Setup skill: {exc}")

    def _read_vocab_speakers(self) -> list[tuple[str, str]]:
        """Parse the '# Speakers' section from glossary.txt and return (orig, tl) pairs."""
        game_root = self.folder_edit.text().strip()
        if not game_root:
            return []
        try:
            vocab_path = ensure_game_glossary(game_root)
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

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3 – Speaker detection
    # ─────────────────────────────────────────────────────────────────────────

    def _copy_speaker_prompt(self):
        # Legacy alias — Project Setup covers speakers analysis.
        self._copy_project_setup_prompt()

    def _copy_wrap_prompt(self):
        self._copy_clipboard_skill(
            "wrap_config.md",
            "Text-wrap analysis prompt copied to clipboard.",
        )

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
            self._refresh_p2_control_dependencies()

    def _refresh_p2_control_dependencies(self, *_args) -> None:
        """Gate Phase 2 child controls behind their audited command types."""
        checks = getattr(self, "_p2_code_checks", {})
        code122 = bool(checks.get("CODE122") and checks["CODE122"].isChecked())
        code357 = bool(checks.get("CODE357") and checks["CODE357"].isChecked())
        code355655 = bool(
            checks.get("CODE355655") and checks["CODE355655"].isChecked()
        )

        range_box = getattr(self, "_p2_var_range_box", None)
        if range_box is not None:
            range_box.setEnabled(code122)

        plugin_group = getattr(self, "_p2_plugin_filter_group", None)
        if plugin_group is not None:
            plugin_group.setEnabled(code357)
        pattern_group = getattr(self, "_p2_pattern_filter_group", None)
        if pattern_group is not None:
            pattern_group.setEnabled(code355655)

        advanced = getattr(self, "_phase2_advanced", None)
        advanced_enabled = code357 or code355655
        if advanced is not None:
            if not advanced_enabled and advanced.toggle.isChecked():
                advanced.toggle.setChecked(False)
            advanced.toggle.setEnabled(advanced_enabled)

        hint = getattr(self, "_p2_advanced_hint", None)
        if hint is not None:
            if code357 and code355655:
                hint.setText(
                    "Both advanced filter lists are unlocked. Choose only entries confirmed "
                    "by the audit."
                )
            elif code357:
                hint.setText(
                    "MZ plugin command filters are unlocked. Script text filters stay locked "
                    "until Scripts (355/655) is enabled."
                )
            elif code355655:
                hint.setText(
                    "Script text filters are unlocked. MZ plugin filters stay locked until "
                    "MZ plugin commands (357) is enabled."
                )
            else:
                hint.setText(
                    "Advanced filters stay locked until their matching text source is "
                    "enabled above."
                )
            hint.setStyleSheet(f"color:{COLORS.text_muted};font-size:12px;")

        any_source = any(cb.isChecked() for cb in checks.values())
        run_button = getattr(self, "_run_p2_btn", None)
        if run_button is not None:
            run_button.setEnabled(any_source)
        banner = getattr(self, "_p2_selection_banner", None)
        if banner is not None:
            if any_source:
                count = sum(cb.isChecked() for cb in checks.values())
                banner.set_status(
                    f"{count} audited source{'s' if count != 1 else ''} selected. "
                    "Review the choices before starting.",
                    "info",
                )
            else:
                banner.set_status(
                    "Select at least one audited event command type above.",
                    "warning",
                )

    def _schedule_p2_config_apply(self, *_args):
        """Debounce auto-saving Phase 2 settings while the user changes controls."""
        self._refresh_p2_control_dependencies()
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

    def _copy_plugins_js_translate_prompt(self):
        is_ace = bool(
            getattr(self, "_ace_rvdata_dir", "") or getattr(self, "_ace_json_dir", "")
        )
        if is_ace:
            self._copy_clipboard_skill(
                "ace_script_translation.md",
                "Ace scripts translation prompt copied to clipboard.",
            )
        else:
            self._copy_clipboard_skill(
                "plugin_translation.md",
                "plugins.js translation prompt copied to clipboard.",
            )

    def _copy_plugin_prompt(self):
        self._copy_clipboard_skill(
            "risky_codes.md",
            "Risky codes analysis prompt copied to clipboard.",
        )

    def _copy_translation_qa_prompt(self):
        """Copy the post-export RPG Maker QA skill with this game's paths."""
        try:
            game_root = self.folder_edit.text().strip()
            if not game_root or not Path(game_root).is_dir():
                self._log("⚠  Select and detect a game folder in Step 0 first.")
                return
            game_data = self._data_path
            if not game_data or not Path(game_data).is_dir():
                self._log("⚠  No game data folder detected. Complete Step 0 first.")
                return
            replacements = {
                "{{GAME_DATA_FOLDER}}": str(Path(game_data).expanduser().resolve()),
                "{{GAME_ROOT}}": str(Path(game_root).expanduser().resolve()),
                "{{VOCAB_FILE}}": str((Path(game_root) / "glossary.txt").expanduser().resolve()),
            }
            prompt = load_clipboard_skill("rpgmaker_translation_qa.md")
            missing = [token for token in replacements if token not in prompt]
            if missing:
                raise ValueError(
                    "Translation QA skill is missing required placeholder(s): "
                    + ", ".join(missing)
                )
            for token, value in replacements.items():
                prompt = prompt.replace(token, value)
            QApplication.clipboard().setText(prompt)
            self._log(f"RPG Maker game-data QA skill copied for {game_data}.")
        except Exception as exc:
            self._log(f"❌ Could not copy translation QA skill: {exc}")

    def _copy_clipboard_skill(self, filename: str, success_message: str):
        try:
            prompt = load_clipboard_skill(filename)
            QApplication.clipboard().setText(prompt)
            self._log(success_message)
        except Exception as exc:
            self._log(f"❌ Could not copy {filename}: {exc}")

    def _load_rewrap_widths(self):
        """Load the four current wrap widths directly from .env."""
        try:
            values = dotenv_values(Path(".env")) if Path(".env").is_file() else {}

            def _value(key: str, fallback: int) -> int:
                raw = values.get(key)
                return int(raw) if raw not in (None, "") else fallback

            dialogue = _value("width", self.wrap_width_spin.value())
            face = _value("faceWidth", max(1, dialogue - 10))
            self.rewrap_dialogue_width.setValue(dialogue)
            self.rewrap_face_width.setValue(min(dialogue, face))
            self.rewrap_list_width.setValue(
                _value("listWidth", self.wrap_list_spin.value())
            )
            self.rewrap_note_width.setValue(
                _value("noteWidth", self.wrap_note_spin.value())
            )
            if self.rewrap_file_list.count():
                self.rewrap_status_label.setText("Loaded current widths from .env.")
            else:
                self.rewrap_status_label.setText(
                    "Loaded .env widths; no game data JSON files are available yet."
                )
        except Exception as exc:
            self.rewrap_status_label.setText(f"Could not load .env widths: {exc}")

    def refresh_wrap_widths_from_env(self):
        """Reload the Phase 1 width controls directly from the current .env file."""
        if not hasattr(self, "wrap_width_spin"):
            return
        try:
            values = dotenv_values(Path(".env")) if Path(".env").is_file() else {}

            def _value(key: str, fallback: int) -> int:
                raw = values.get(key)
                try:
                    return int(raw) if raw not in (None, "") else fallback
                except (TypeError, ValueError):
                    return fallback

            dialogue = _value("width", 60)
            face = _value("faceWidth", 50)
            self.wrap_width_spin.setValue(dialogue)
            self.wrap_face_spin.setValue(min(dialogue, face))
            self.wrap_list_spin.setValue(_value("listWidth", 100))
            self.wrap_note_spin.setValue(_value("noteWidth", 75))
        except Exception as exc:
            self._log(f"⚠  Could not load line widths from .env: {exc}")

    def _rewrap_data_directory(self) -> Path | None:
        """Return the Step-0 game data directory used by direct rewrapping."""
        candidates: list[Path] = []
        if self._data_path:
            candidates.append(Path(self._data_path))
        game_root = self.folder_edit.text().strip() if hasattr(self, "folder_edit") else ""
        if game_root:
            root = Path(game_root)
            candidates.extend(
                (root / "data", root / "www" / "data", root / "ace_json", root / "JSON")
            )
        for candidate in candidates:
            if candidate.is_dir():
                return candidate.expanduser().resolve()
        return None

    def _refresh_rewrap_files(self):
        """Refresh the checkable game-data JSON scope without losing choices."""
        if not hasattr(self, "rewrap_file_list"):
            return
        previous = {
            self.rewrap_file_list.item(i).data(Qt.UserRole):
            self.rewrap_file_list.item(i).checkState() == Qt.Checked
            for i in range(self.rewrap_file_list.count())
        }
        data_directory = self._rewrap_data_directory()
        paths = (
            sorted(data_directory.glob("*.json"), key=lambda p: p.name.casefold())
            if data_directory is not None
            else []
        )
        first_load = not previous
        self.rewrap_file_list.clear()
        for path in paths:
            item = QListWidgetItem(path.name)
            item.setData(Qt.UserRole, path.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if previous.get(path.name, first_load) else Qt.Unchecked
            )
            self.rewrap_file_list.addItem(item)
        self._filter_rewrap_files(self.rewrap_file_filter.text())
        if data_directory is not None:
            self.rewrap_scope_title.setText(f"Source · {data_directory}")
            self.rewrap_scope_title.setToolTip(str(data_directory))
        else:
            self.rewrap_scope_title.setText("Source unavailable · complete Step 0 first")
            self.rewrap_scope_title.setToolTip("")
        if paths:
            self.rewrap_status_label.setText(
                f"Loaded {len(paths)} game data JSON file(s). Scan before applying."
            )
        else:
            self.rewrap_status_label.setText(
                "No game data JSON files found. Complete Step 0 and export translations first."
            )

    def _filter_rewrap_files(self, text: str):
        needle = str(text or "").strip().casefold()
        if not hasattr(self, "rewrap_file_list"):
            return
        for i in range(self.rewrap_file_list.count()):
            item = self.rewrap_file_list.item(i)
            item.setHidden(bool(needle and needle not in item.text().casefold()))

    def _select_rewrap_files(self, mode: str):
        if not hasattr(self, "rewrap_file_list"):
            return
        for i in range(self.rewrap_file_list.count()):
            item = self.rewrap_file_list.item(i)
            name = str(item.data(Qt.UserRole) or item.text())
            if mode == "all":
                checked = True
            elif mode == "none":
                checked = False
            elif mode == "db":
                checked = name in _DB_FILES
            elif mode == "events":
                checked = (
                    name.startswith("Map") and name != "MapInfos.json"
                ) or name in _EVENT_FILES_EXACT
            else:
                checked = False
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _selected_rewrap_files(self) -> list[str]:
        return [
            str(self.rewrap_file_list.item(i).data(Qt.UserRole))
            for i in range(self.rewrap_file_list.count())
            if self.rewrap_file_list.item(i).checkState() == Qt.Checked
        ]

    def _rewrap_options(self):
        from util.rpgmaker_rewrap import (
            DIALOGUE,
            FACE_DIALOGUE,
            LIST_HELP,
            NOTES,
            RewrapOptions,
            parse_event_codes,
        )

        categories = set()
        if self.rewrap_dialogue_cb.isChecked():
            categories.add(DIALOGUE)
        if self.rewrap_face_cb.isChecked():
            categories.add(FACE_DIALOGUE)
        if self.rewrap_list_cb.isChecked():
            categories.add(LIST_HELP)
        if self.rewrap_notes_cb.isChecked():
            categories.add(NOTES)
        if not categories:
            raise ValueError("Select at least one text category")
        return RewrapOptions(
            dialogue_width=self.rewrap_dialogue_width.value(),
            face_dialogue_width=min(
                self.rewrap_dialogue_width.value(), self.rewrap_face_width.value()
            ),
            list_width=self.rewrap_list_width.value(),
            note_width=self.rewrap_note_width.value(),
            categories=frozenset(categories),
            event_codes=parse_event_codes(self.rewrap_codes_edit.text()),
            max_protected_rows=(
                self.rewrap_max_rows_spin.value()
                if self.rewrap_skip_overflow_cb.isChecked()
                else 0
            ),
            skip_protected_overflow=self.rewrap_skip_overflow_cb.isChecked(),
        )

    def _run_rewrap(self, apply: bool):
        if getattr(self, "_rewrap_worker", None) is not None:
            self._log("⚠  A rewrap scan is already running.")
            return
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(
                self, "Busy", "Wait for the current workflow task to finish before rewrapping."
            )
            return
        data_directory = self._rewrap_data_directory()
        if data_directory is None:
            QMessageBox.warning(
                self,
                "Rewrap",
                "No game data folder is available. Complete Step 0 and export first.",
            )
            return
        file_names = self._selected_rewrap_files()
        if not file_names:
            QMessageBox.warning(self, "Rewrap", "Select at least one game data JSON file.")
            return
        try:
            options = self._rewrap_options()
        except ValueError as exc:
            QMessageBox.warning(self, "Rewrap", str(exc))
            return

        if apply:
            categories = ", ".join(sorted(options.categories))
            codes = (
                "all supported"
                if options.event_codes is None
                else ", ".join(str(code) for code in sorted(options.event_codes))
            )
            row_protection = (
                f"skip non-401 fields over {options.max_protected_rows} rows"
                if options.skip_protected_overflow
                else "off"
            )
            answer = QMessageBox.question(
                self,
                "Rewrap Exported Game Data",
                f"Deterministically rewrap {len(file_names)} file(s) directly in:\n"
                f"{data_directory}\n\n"
                f"Categories: {categories}\n"
                f"Event codes: {codes}\n"
                f"Widths: dialogue {options.dialogue_width}, face {options.face_dialogue_width}, "
                f"list {options.list_width}, notes {options.note_width}\n"
                f"Non-401 row protection: {row_protection}\n\n"
                "This edits the game data in place, does not call the translation model, "
                "and never edits _original. Keep a game backup before continuing.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self.rewrap_scan_btn.setEnabled(False)
        self.rewrap_apply_btn.setEnabled(False)
        self.rewrap_results.clear()
        self._rewrap_results_disclosure.toggle.setChecked(True)
        self.rewrap_status_label.setText(
            "Rewrapping selected files…" if apply else "Scanning selected files…"
        )
        worker = _RpgMakerRewrapWorker(
            str(data_directory), options, file_names, apply=apply
        )
        self._rewrap_worker = worker
        worker.done.connect(self._on_rewrap_done)
        worker.failed.connect(self._on_rewrap_failed)
        worker.finished.connect(self._release_rewrap_worker)
        worker.start()

    def _on_rewrap_done(self, report, apply: bool):
        self.rewrap_status_label.setText(report.headline(apply=apply))
        for preview in report.previews:
            item = QListWidgetItem(preview.summary())
            item.setToolTip(f"Before:\n{preview.before}\n\nAfter:\n{preview.after}")
            self.rewrap_results.addItem(item)
        if report.changes_found > len(report.previews):
            self.rewrap_results.addItem(
                f"… {report.changes_found - len(report.previews)} additional change(s) not shown"
            )
        for error in report.errors:
            self.rewrap_results.addItem(f"⚠ {error}")
        self._log(("✅  " if not report.errors else "⚠  ") + report.headline(apply=apply))
        if apply and report.files_written:
            data_directory = self._rewrap_data_directory()
            self._log(
                f"   Rewrapped {data_directory or 'game data'} in place; "
                "_original values were preserved."
            )

    def _on_rewrap_failed(self, message: str):
        self._rewrap_results_disclosure.toggle.setChecked(True)
        self.rewrap_status_label.setText(f"Rewrap failed: {message}")
        self.rewrap_results.addItem(f"❌ {message}")
        self._log(f"❌ Rewrap failed: {message}")

    def _release_rewrap_worker(self):
        self.rewrap_scan_btn.setEnabled(True)
        self.rewrap_apply_btn.setEnabled(True)
        worker = getattr(self, "_rewrap_worker", None)
        if worker is not None:
            worker.deleteLater()
        self._rewrap_worker = None

    def _apply_wrap_config(self):
        """Write dialogue, face-dialogue, list, and note widths back into .env."""
        import re as _re
        updates = {
            "width":     str(self.wrap_width_spin.value()),
            "faceWidth": str(min(self.wrap_width_spin.value(), self.wrap_face_spin.value())),
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
        batch = self._workflow_batch_mode()
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
            label = "Phase 0 (core DB files)" + (" — batch" if batch else "")
            file_preset = "db"
        elif phase == 1:
            config = dict(PHASE1_CONFIG)
            config["CODE408"] = bool(
                getattr(self, "_phase1_code408_cb", None)
                and self._phase1_code408_cb.isChecked()
            )
            label = "Phase 1 (safe codes)" + (" — batch" if batch else "")
            file_preset = "events"
        elif phase == "1b":
            config = PHASE1B_CONFIG
            label = "Phase 1b (code 111 cache)" + (" — batch" if batch else "")
            file_preset = "events"
        else:
            # Build Phase 2 config: start from PHASE2_CONFIG defaults, then overlay checkbox states
            config = dict(PHASE2_CONFIG)
            for code_key, cb in getattr(self, "_p2_code_checks", {}).items():
                config[code_key] = cb.isChecked()
            label = "Phase 2 (risky codes)" + (" — batch" if batch else "")
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
        mode_text = self._workflow_mode_text()
        self._navigate_to_translation(file_preset, auto_start=True, mode_text=mode_text)

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

            # 5. Navigate to Translation tab
            if hasattr(pw, "switch_page"):
                page = getattr(pw, "PAGE_TRANSLATION", 4)
                pw.switch_page(page)
            elif hasattr(pw, "content_stack"):
                pw.content_stack.setCurrentIndex(4)
                if hasattr(pw, "nav_buttons"):
                    for i, btn in enumerate(pw.nav_buttons):
                        btn.setChecked(i == 4)

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
    # Step 5 – Export to game
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
        if self._rewrap_worker is not None and self._rewrap_worker.isRunning():
            QMessageBox.information(
                self, "Busy", "Wait for the rewrap scan/write to finish before exporting."
            )
            return
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
            "Export Selected Files to Game",
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
        if self._rewrap_worker is not None and self._rewrap_worker.isRunning():
            QMessageBox.information(
                self, "Busy", "Wait for the rewrap scan/write to finish before exporting."
            )
            return
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

    def _create_public_release(self):
        game_root = self.folder_edit.text().strip()
        if not game_root or not Path(game_root).is_dir():
            QMessageBox.warning(
                self,
                "No game folder",
                "Select and detect a game folder in Step 0 first.",
            )
            return
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Busy", "A task is already running. Please wait.")
            return

        from util.release_package import default_release_zip_path

        suggested = str(default_release_zip_path(game_root))
        output, _ = QFileDialog.getSaveFileName(
            self,
            "Build Public Release ZIP",
            suggested,
            "ZIP archives (*.zip)",
        )
        if not output:
            return

        self._log(f"Creating public release ZIP from {game_root} …")
        worker = _ReleaseZipWorker(game_root, output)
        self._worker = worker
        release_buttons = (
            getattr(self, "_release_zip_btn", None),
            getattr(self, "_ace_release_zip_btn", None),
        )
        for button in release_buttons:
            if button is not None:
                button.setEnabled(False)

        def finished():
            if self._worker is worker:
                self._worker = None
            for button in release_buttons:
                if button is not None:
                    button.setEnabled(True)

        def failed(message: str):
            self._log(f"❌ Public release ZIP: {message}")
            QMessageBox.warning(self, "Release ZIP failed", message)

        worker.done.connect(self._on_public_release_done)
        worker.error.connect(failed)
        worker.finished.connect(finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_public_release_done(self, result):
        size_mb = result.output_path.stat().st_size / (1024 * 1024)
        message = (
            f"Created {result.output_path.name} ({size_mb:.1f} MB) with "
            f"{result.files_added} file(s); omitted {result.excluded_entries} "
            "tool/private item(s)."
        )
        self._log(f"✅ {message}")
        QMessageBox.information(
            self,
            "Public Release ZIP created",
            f"{message}\n\nSaved to:\n{result.output_path}",
        )

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
        from util.ace.update_tools import ace_tool_path
        return ace_tool_path(name)

    def _ensure_ace_tools(self) -> bool:
        from util.ace.update_tools import ensure_ace_tools
        return ensure_ace_tools(log_fn=self._log)

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
        if not self._ensure_ace_tools():
            return
        try:
            from util.ace.update_tools import build_decrypter_command
            cmd = build_decrypter_command(Path(game_root))
        except FileNotFoundError as exc:
            self._log(f"❌ {exc}")
            return
        decrypter = Path(cmd[0])
        self._log(f"Running {decrypter.name} in {game_root} …")
        w = _SubprocessWorker(cmd, cwd=game_root, label=decrypter.stem)
        w.log.connect(self._log)
        w.done.connect(lambda ok, msg: self._log(("✅ " if ok else "❌ ") + msg))
        self._worker = w
        w.start()

    def _run_rv2json_create(self):
        """Run RV2JSON.exe -c to convert rvdata2 → JSON files (run from game root)."""
        if not self._ensure_ace_tools():
            return
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
                "color:#f2c94c;font-size:13px;padding:4px 8px;"
                "background-color:#2b2010;border:1px solid #5a4010;"
                "border-radius:4px;margin:4px 0;"
            )
            return

        self._log(f"JSON files ready in: {ace_json}")
        self.detected_label.setText(
            f"Engine: Ace (via RV2JSON)   ·   ace_json: {ace_json}"
        )
        self.detected_label.setStyleSheet(
            "color:#73c991;font-size:13px;padding:4px 8px;"
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
        if not self._ensure_ace_tools():
            return
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
        w = _FileCopyWorker(src, dst, skip_names=_RPG_GAMEUPDATE_COPY_SKIP_NAMES)
        w.log.connect(self._log)
        w.done.connect(self._on_gameupdate_done)
        self._worker = w
        w.start()

    def _on_gameupdate_done(self, count: int, errors: list):
        self._log(f"✅ gameupdate: copied {count} file(s).")
        for e in errors:
            self._log(f"   ⚠  {e}")
        dst = self.folder_edit.text().strip()
        if dst and not errors:
            self._write_gameupdate_patch_config(dst)

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
            queue.append((
                "[C] gameupdate copy",
                _FileCopyWorker(
                    gameupdate_src,
                    game_root_dst,
                    skip_names=_RPG_GAMEUPDATE_COPY_SKIP_NAMES,
                ),
            ))
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
                    if not errors and game_root_dst:
                        self._write_gameupdate_patch_config(game_root_dst)
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
        panel = getattr(self, "_activity_panel", None)
        if panel is None:
            return
        _clean, kind = panel.append_message(message)
        if not panel.isVisible():
            self._activity_unread += 1
            if kind == "error":
                self._activity_errors += 1
            self._refresh_activity_badge()

    def _setting(self, key: str, default=None):
        if self.settings:
            return self.settings.value(f"workflow/{key}", default)
        return default

    def _save_setting(self, key: str, value):
        if self.settings:
            self.settings.setValue(f"workflow/{key}", value)
