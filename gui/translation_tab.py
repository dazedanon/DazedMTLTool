#!/usr/bin/env python3
"""
Simple Translation Tab for DazedTL GUI

Simple file management and translation execution with console log display.
"""

import os
import datetime
import json
import subprocess
import threading
import sys
import io
import time
from contextlib import redirect_stdout
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
import traceback
import signal
import multiprocessing
import re
from importlib import import_module
from colorama import Fore
from tqdm import tqdm
from dotenv import dotenv_values, load_dotenv
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QGroupBox,
    QTextEdit, QMessageBox, QListWidget, QListWidgetItem, QLineEdit,
    QSplitter, QFileDialog, QComboBox, QCheckBox, QProgressBar, QFrame, QFormLayout, QStackedWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea, QMenu,
)
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QMutex, QProcess, QSettings, QSize
from PyQt5.QtGui import QFont, QColor, QBrush
from gui.log_viewer import LogViewer
from gui import qt_icons
from gui.translation_context_dialog import TranslationContextDialog
from util.skills import load_generic_project_setup
from util.game_settings import load_game_wrap_widths, normalize_wrap_widths
from util.paths import (
    APP_NAME,
    GAME_GLOSSARY_RELATIVE,
    GAME_QUIRKS_RELATIVE,
    GAME_SKILL_RELATIVE,
    GAME_SKILL_RESERVED_NAMES,
    GAME_SKILLS_RELATIVE,
    GLOSSARY_BASE_ENABLED_ENV,
    GLOSSARY_OVERRIDE_ENV,
    LEGACY_GAME_SKILLS_RELATIVE,
    LEGACY_QUIRKS_FILENAME,
    ORG_NAME,
    PROJECT_ROOT,
    prepare_game_translation_context,
)
from gui.theme import COLORS, Geometry, Spacing
from gui.ui_components import (
    CheckableFileList,
    PageHeader,
    SectionCard,
    action_button_width_hint,
    configure_action_button,
    equalize_button_widths,
    refresh_style,
)


def _strip_ansi(text):
    if not isinstance(text, str) or not text:
        return text
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def _mismatch_summary(count):
    count = max(0, int(count or 0))
    noun = "mismatch" if count == 1 else "mismatches"
    return f"{count} validation {noun}"


def create_section_header(title):
    """Create a clean section header without boxes."""
    return qt_icons.make_section_header(
        title,
        "QLabel {"
        "font-size: 13px;"
        "font-weight: bold;"
        f"color: {COLORS.accent_text};"
        "padding: 8px 0px 5px 0px;"
        "background-color: transparent;"
        "}",
    )

def create_horizontal_line():
    """Create a horizontal separator line."""
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setStyleSheet(f"QFrame {{ color: {COLORS.border}; margin: 4px 0px; }}")
    return line


BATCH_MODE_LABEL = "Batch Translate"


def _configured_game_root(settings, module_name: str = "") -> str:
    """Return the selected engine's game root, with legacy-key fallback."""
    if settings is None:
        return ""
    normalized_module = module_name.casefold()
    if "wolfdawn" in normalized_module:
        # The unscoped legacy key belonged to the RPG Maker workflow. Reusing
        # it here can inject an RPG project's context into a WolfDawn run.
        keys = ("wolf_workflow/last_game_folder",)
    elif not normalized_module or "rpg maker mv/mz" in normalized_module:
        keys = ("workflow/last_game_folder", "last_game_folder")
    else:
        # Other translation modules do not have a workflow-backed project
        # selector. Reusing RPG Maker's last folder would inject unrelated
        # glossary/skill guidance and can block a run on a stale path.
        return ""
    for key in keys:
        value = str(settings.value(key, "") or "").strip()
        if value:
            return value
    return ""


def _validate_configured_game_root(game_root: str, module_name: str) -> None:
    """Reject stale settings before portable guidance can be migrated."""
    from util.project_scanner import detect_wolf_layout, find_data_folder

    root = Path(game_root)
    normalized_module = module_name.casefold()
    if "wolfdawn" in normalized_module:
        if detect_wolf_layout(root).get("engine") != "WOLF":
            raise ValueError(
                f"The configured folder is not a recognized WOLF project: {root}"
            )
        return

    if not normalized_module or "rpg maker mv/mz" in normalized_module:
        if any(root.glob("Game.rgss*")):
            return
        data_path, engine = find_data_folder(root)
        if data_path is None or engine not in {"MVMZ", "ACE"}:
            raise ValueError(
                f"The configured folder is not a recognized RPG Maker project: {root}"
            )


def _activate_game_context_root(
    game_root: str | Path | None,
    module_name: str = "",
    *,
    validate_engine: bool = True,
) -> tuple[str, dict[str, int]]:
    """Activate one project's glossary, skill overlays, and wrapping widths."""
    defaults = (
        dotenv_values(PROJECT_ROOT / ".env")
        if (PROJECT_ROOT / ".env").is_file()
        else {}
    )
    widths = normalize_wrap_widths(defaults)
    game_root = str(game_root or "").strip()
    # Invalidate the prior project before attempting a switch. A failed switch
    # must never leave another game's root or widths active in this process.
    os.environ.pop("DAZED_GAME_ROOT", None)
    os.environ.pop(GLOSSARY_OVERRIDE_ENV, None)
    os.environ.pop(GLOSSARY_BASE_ENABLED_ENV, None)
    for key, value in widths.items():
        os.environ[key] = str(value)

    if not game_root:
        return "", widths
    if not Path(game_root).is_dir():
        raise FileNotFoundError(
            f"The configured game folder no longer exists: {game_root}"
        )

    if validate_engine:
        _validate_configured_game_root(game_root, module_name)
    saved = load_game_wrap_widths(game_root)
    prepare_game_translation_context(game_root)
    if saved is not None:
        widths = saved
    os.environ["DAZED_GAME_ROOT"] = game_root
    for key, value in widths.items():
        os.environ[key] = str(value)
    return game_root, widths


def _activate_configured_game_context(
    settings, module_name: str = ""
) -> tuple[str, dict[str, int]]:
    """Activate the configured game's complete translation context."""
    return _activate_game_context_root(
        _configured_game_root(settings, module_name), module_name
    )


def _translation_context_inventory(game_root: str | Path | None) -> dict[str, object]:
    """Describe portable/legacy context files without migrating or creating them."""
    value = str(game_root or "").strip()
    inventory: dict[str, object] = {
        "root": "",
        "glossary": None,
        "game": None,
        "quirks": None,
        "custom": [],
    }
    if not value:
        return inventory

    root = Path(value).expanduser()
    inventory["root"] = str(root)
    if not root.is_dir():
        return inventory

    def first_regular_file(*paths: Path) -> Path | None:
        return next(
            (
                path
                for path in paths
                if path.is_file() and not path.is_symlink()
            ),
            None,
        )

    portable_skills = root / GAME_SKILLS_RELATIVE
    legacy_skills = root / LEGACY_GAME_SKILLS_RELATIVE
    inventory["glossary"] = first_regular_file(
        root / GAME_GLOSSARY_RELATIVE,
        root / "glossary.txt",
    )
    inventory["game"] = first_regular_file(
        root / GAME_SKILL_RELATIVE,
        portable_skills / "translation.md",
        legacy_skills / "game.md",
        legacy_skills / "translation.md",
    )
    inventory["quirks"] = first_regular_file(
        root / GAME_QUIRKS_RELATIVE,
        root / LEGACY_QUIRKS_FILENAME,
        legacy_skills / "quirks.md",
    )

    reserved = {name.casefold() for name in GAME_SKILL_RESERVED_NAMES}
    custom: list[Path] = []
    for directory in (portable_skills, legacy_skills):
        if not directory.is_dir() or directory.is_symlink():
            continue
        custom.extend(
            path
            for path in sorted(directory.glob("*.md"), key=lambda item: item.name.casefold())
            if path.name.casefold() not in reserved
            and path.is_file()
            and not path.is_symlink()
        )
    inventory["custom"] = custom
    return inventory


BATCH_MODE_BENEFIT_NOTE = (
    "Provider Batch API — typically 50% cheaper than live translation (Claude, GPT, or Gemini)."
)
BATCH_COLLECT_LIVE_CHARGE_NOTE = (
    "Before a fresh batch, unresolved RPG Maker and WolfDawn speaker names are scanned "
    "and translated into the game glossary (with approval) so nameplates are not left "
    "in Japanese while dialogue is batched."
)

_CONFIG_UNSET = object()


def _format_estimated_cost(value) -> str:
    """Show useful precision for small runs without noisy large totals."""
    amount = float(value or 0)
    return f"${amount:.4f}" if abs(amount) < 1 else f"${amount:.2f}"


def default_translation_mode(model=_CONFIG_UNSET, api_url=_CONFIG_UNSET,
                             api_provider=_CONFIG_UNSET) -> str:
    """Choose Batch when the configured route has a supported asynchronous API."""
    if model is _CONFIG_UNSET or api_url is _CONFIG_UNSET or api_provider is _CONFIG_UNSET:
        env = dotenv_values(PROJECT_ROOT / ".env") if (PROJECT_ROOT / ".env").exists() else {}
        if model is _CONFIG_UNSET:
            model = env.get("model", os.getenv("model", ""))
        if api_url is _CONFIG_UNSET:
            api_url = env.get("api", os.getenv("api", ""))
        if api_provider is _CONFIG_UNSET:
            api_provider = env.get("API_PROVIDER", os.getenv("API_PROVIDER", "openai"))

    from util.translation import isBatchSupported

    provider = None if api_provider is _CONFIG_UNSET else api_provider
    return BATCH_MODE_LABEL if isBatchSupported(
        str(model or ""), api_url, provider
    ) else "Translate"


def _should_prepare_speakers_automatically(
    module_name,
    *,
    estimate_only=False,
    parse_speakers=False,
    batch_mode=False,
    batch_resume_state=None,
) -> bool:
    """Decide whether translation should resolve speakers before file work.

    WolfDawn always auto-preflights on a fresh run. RPG Maker normally relies on
    Workflow "Collect names", but batch collect/consume cannot live-translate
    speakers - unresolved FIRSTLINESPEAKERS (and other nameplates) would stay
    Japanese while dialogue is batched. Fresh RPG Maker batches therefore run
    the same unresolved-speaker preflight.
    """
    name = str(module_name or "").casefold()
    if estimate_only or parse_speakers or (batch_mode and batch_resume_state):
        return False
    if "wolfdawn" in name:
        return True
    if batch_mode and ("mv/mz" in name or "rpg maker" in name):
        return True
    return False


TRANSLATION_MODULE_SPECS = (
    ("RPG Maker MV/MZ", (".json",), "modules.rpgmakermvmz", "handleMVMZ"),
    ("CSV", (".csv",), "modules.csv", "handleCSV"),
    ("Tyrano", (".ks",), "modules.tyrano", "handleTyrano"),
    ("Kirikiri", (".ks",), "modules.kirikiri", "handleKirikiri"),
    ("JSON", (".json",), "modules.json", "handleJSON"),
    ("Lune", (".l",), "modules.lune", "handleLune"),
    ("Yuris", (".json",), "modules.yuris", "handleYuris"),
    ("NScript", (".nscript",), "modules.nscript", "handleOnscripter"),
    ("Wolf RPG (WolfDawn)", (".json",), "modules.wolfdawn", "handleWolfDawn"),
    ("Wolf RPG", (".json",), "modules.wolf", "handleWOLF"),
    ("Wolf RPG 2", (".txt",), "modules.wolf2", "handleWOLF2"),
    ("Regex", (".txt", ".json", ".script", ".csv"), "modules.regex", "handleRegex"),
    ("Text", (".txt", ".srt"), "modules.text", "handleText"),
    ("RenPy", (".rpy",), "modules.renpy", "handleRenpy"),
    ("Unity", (".unity",), "modules.unity", "handleUnity"),
    # The strings the semi-manual image workflow exported. Declared by whole
    # filename rather than ".json" so it never offers up a folder of RPG Maker
    # data - the match below is endswith, so both forms work here.
    ("Image Text", ("image_text.json",), "modules.imagetext", "handleImageText"),
    ("RPG Maker Plugin", (".js",), "modules.rpgmakerplugin", "handlePlugin"),
    ("Aquedi4 Prepared JSON", (".json",), "modules.aquedi4", "handleAquedi4"),
    ("SRPG Studio", (".json",), "modules.srpg", "handleSRPG"),
)


def _lazy_module_handler(module_name, handler_name):
    """Return a handler that imports its engine only when translation starts."""

    def run(*args, **kwargs):
        module = import_module(module_name)
        return getattr(module, handler_name)(*args, **kwargs)

    return run


class _ShimLabel:
    """Plain stand-in for QLabel used by Files-tab row helpers (no real Qt widget)."""

    def __init__(self, text=""):
        self._text = text
        self._style = ""
        self._visible = False
        self._tooltip = ""

    def setText(self, text):
        self._text = text or ""

    def text(self):
        return self._text

    def setStyleSheet(self, style):
        self._style = style or ""

    def setVisible(self, visible):
        self._visible = bool(visible)

    def setToolTip(self, tip):
        self._tooltip = tip or ""

    def toolTip(self):
        return self._tooltip


class _ShimCheckBox:
    def __init__(self):
        self._checked = False
        self._enabled = False
        self._visible = False

    def setChecked(self, checked):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked

    def setEnabled(self, enabled):
        self._enabled = bool(enabled)

    def setVisible(self, visible):
        self._visible = bool(visible)


class _ShimProgressBar:
    def __init__(self):
        self._value = 0
        self._maximum = 100
        self._visible = False
        self._text_visible = True
        self._style = ""

    def setValue(self, value):
        self._value = int(value)

    def setMaximum(self, maximum):
        self._maximum = int(maximum)

    def setVisible(self, visible):
        self._visible = bool(visible)

    def setTextVisible(self, visible):
        self._text_visible = bool(visible)

    def setStyleSheet(self, style):
        self._style = style or ""


class _ShimWidget:
    def __init__(self):
        self._visible = False
        self._tooltip = ""

    def setVisible(self, visible):
        self._visible = bool(visible)

    def setToolTip(self, tip):
        self._tooltip = tip or ""


class TranslationWorker(QThread):
    """Worker thread for running translations without blocking the UI."""
    
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int, str)  # current_file, total_files, filename
    item_progress_signal = pyqtSignal(str, int, int)  # filename, current_item, total_items (for tqdm within file)
    file_error_signal = pyqtSignal(str, str)  # filename, error_message
    # Soft validation failure: original kept for bad chunks; run can still succeed.
    file_mismatch_signal = pyqtSignal(str, str)  # filename, message
    status_signal = pyqtSignal(str)  # updates the top translating_label from the worker
    finished_signal = pyqtSignal(bool, str)
    batch_phase_signal = pyqtSignal(str, object)  # phase name, optional payload
    speaker_confirmation_signal = pyqtSignal(object)  # names plus local token/cost estimate
    
    def __init__(self, project_root, module_info, estimate_only=False, selected_files=None,
                 parse_speakers=False, batch_mode=False, batch_resume_state=None,
                 batch_workflow_return=None):
        super().__init__()
        self.project_root = project_root
        self.module_info = module_info  # [name, extensions, handler_function]
        self.estimate_only = estimate_only
        self.selected_files = selected_files  # List of files to process
        # Whether we should run in speaker-parse mode (special-case for MV/MZ)
        self.parse_speakers = parse_speakers
        self.batch_mode = batch_mode
        self.batch_resume_state = batch_resume_state
        self.batch_workflow_return = (
            dict(batch_workflow_return)
            if isinstance(batch_workflow_return, dict)
            else None
        )
        self.batch_runtime_profile = None
        self._batch_submit_event = threading.Event()
        self._batch_submit_approved = False
        self._batch_pending_estimate = None
        self._speaker_confirm_event = threading.Event()
        self._speaker_translation_approved = False
        self.should_stop = False
        self.mutex = QMutex()  # For thread safety
        self.executor = None  # Store reference to executor for proper shutdown
        self.running_processes = []  # Track running processes for termination

    def set_batch_submit_response(self, approved):
        """Called from the UI thread after the submit-batch confirmation dialog."""
        self._batch_submit_approved = approved
        self._batch_submit_event.set()

    def set_speaker_translation_response(self, approved):
        """Resume a speaker preflight after the UI confirms or cancels it."""
        self._speaker_translation_approved = bool(approved)
        self._speaker_confirm_event.set()

    def _wait_speaker_translation(self, speakers, estimate=None):
        self._speaker_translation_approved = False
        self._speaker_confirm_event.clear()
        payload = dict(estimate or {})
        payload["speakers"] = list(speakers)
        self.speaker_confirmation_signal.emit(payload)
        self._speaker_confirm_event.wait()
        return self._speaker_translation_approved

    @staticmethod
    def _estimate_grouped_speakers(speakers, history, config, model):
        """Estimate grouped speaker requests locally without calling a model API."""
        from util.translation import (
            countTokens,
            createContext,
            getPricingConfig,
            isClaudeNative,
        )

        names = [str(name).strip() for name in speakers if str(name).strip()]
        batch_size = max(1, int(getattr(config, "batchSize", 1) or 1))
        max_history = max(1, int(getattr(config, "maxHistory", 10) or 10))
        model_name = str(model or getattr(config, "model", "") or "Unknown")
        pricing = getPricingConfig(model_name)
        input_rate = float(pricing["inputAPICost"]) / 1_000_000
        output_rate = float(pricing["outputAPICost"]) / 1_000_000
        native_claude = isClaudeNative(model_name)

        input_tokens = 0
        output_tokens = 0
        estimated_cost = 0.0
        seen_batch_sizes = set()
        current_history = history

        for offset in range(0, len(names), batch_size):
            name_batch = names[offset:offset + batch_size]
            request_payload = json.dumps(
                {f"Line{index + 1}": value for index, value in enumerate(name_batch)},
                indent=4,
                ensure_ascii=False,
            )
            static_system, vocab_text, user = createContext(
                config, request_payload, "json", current_history
            )
            request_tokens = countTokens(
                static_system + vocab_text, user, current_history
            )
            request_input = max(0, int(request_tokens[0]))
            request_output = max(0, int(request_tokens[1]))
            input_tokens += request_input
            output_tokens += request_output

            if native_claude:
                static_tokens = countTokens(static_system, "", "")[0]
                regular_tokens = max(0, request_input - static_tokens)
                # Match the translator's conservative cold-cache estimate: the
                # first request for each output-schema size writes the cached
                # prompt; repeated sizes receive the cache-read discount.
                cache_multiplier = 2.0 if len(name_batch) not in seen_batch_sizes else 0.10
                estimated_cost += (
                    static_tokens * input_rate * cache_multiplier
                    + regular_tokens * input_rate
                    + request_output * output_rate
                )
                seen_batch_sizes.add(len(name_batch))
            else:
                estimated_cost += (
                    request_input * input_rate + request_output * output_rate
                )
            current_history = name_batch[-max_history:]

        return {
            "model": model_name,
            "request_count": (len(names) + batch_size - 1) // batch_size,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost": estimated_cost,
            "cold_cache": native_claude,
        }

    def _wait_batch_submit(self, estimate):
        self._batch_pending_estimate = estimate
        self._batch_submit_approved = False
        self._batch_submit_event.clear()
        self.batch_phase_signal.emit("submit", estimate)
        self._batch_submit_event.wait()
        if not self._batch_submit_approved:
            from util.translation import clearBatchFiles
            clearBatchFiles(strict=True)
        return self._batch_submit_approved

    def _emit_batch_phase(self, phase, payload=None):
        self.batch_phase_signal.emit(phase, payload)

    def _emit_batch_output(self, fn, *args, **kwargs):
        """Run a batch helper that prints status lines; forward them to the log."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = fn(*args, **kwargs)
        for line in buf.getvalue().splitlines():
            if line.strip():
                self.emit_log(line)
        return result

    def _run_batch_poll_fetch(self):
        """Submit (if needed), poll until ended, fetch results. None if stopped while polling."""
        from util.translation import (
            submitTranslationBatches,
            fetchTranslationBatches,
            _read_batch_file,
            BATCH_STATE_FILE,
            _batch_file_lock,
        )

        with _batch_file_lock():
            state = _read_batch_file(BATCH_STATE_FILE)
        if not state.get("batches") or state.get("status") == "partially_submitted":
            est = self._batch_pending_estimate
            file_set = list(self.selected_files or [])
            if not self._emit_batch_output(
                submitTranslationBatches,
                file_set=file_set,
                cost_estimate=est,
            ):
                return 0, 0

        poll = int(os.getenv("batchPollInterval", "60") or 60)
        self._emit_batch_phase("polling")
        self.emit_log(
            f"[BATCH] polling every {poll}s (stop is safe - resume later with Batch Translate mode)..."
        )
        from util.translation import checkTranslationBatchStatuses
        while True:
            if self.should_stop:
                self.emit_log("[BATCH] Stopped while polling. Batch keeps processing - resume later.")
                return None
            buf = io.StringIO()
            with redirect_stdout(buf):
                ended, statuses = checkTranslationBatchStatuses(print_status=True)
            for line in buf.getvalue().splitlines():
                if line.strip():
                    self.emit_log(line)
            if statuses:
                self._emit_batch_phase("poll_status", statuses)
            if ended:
                break
            for _ in range(poll * 10):
                if self.should_stop:
                    self.emit_log("[BATCH] Stopped while polling. Batch keeps processing - resume later.")
                    return None
                time.sleep(0.1)

        fetched, errored = self._emit_batch_output(fetchTranslationBatches)
        return fetched, errored
        
    def stop(self):
        """Stop the translation process."""
        self.mutex.lock()
        try:
            if self.should_stop:
                # Already stopping, don't log again
                return
                
            self.should_stop = True
            self._speaker_translation_approved = False
            self._speaker_confirm_event.set()
            self.emit_log("🛑 Stopping translation worker and canceling pending tasks...")
            
            # Shutdown the executor if it exists
            if self.executor:
                # For older Python versions compatibility, use shutdown(wait=False)
                # and manually cancel futures
                try:
                    # Try to use cancel_futures parameter (Python 3.9+)
                    self.executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    # Fallback for older Python versions
                    self.executor.shutdown(wait=False)
            
            # Terminate any running processes
            if self.running_processes:
                self.emit_log("🛑 Terminating running translation processes...")
                for process in self.running_processes:
                    try:
                        if process.poll() is None:  # Process is still running
                            process.terminate()
                            # Give it a moment to terminate gracefully
                            try:
                                process.wait(timeout=2)
                            except subprocess.TimeoutExpired:
                                # Force kill if it doesn't terminate
                                process.kill()
                                process.wait()
                    except Exception as e:
                        self.emit_log(f"⚠️ Warning: Could not terminate process: {e}")
                self.running_processes.clear()
        finally:
            self.mutex.unlock()
        
    def emit_log(self, message):
        """Thread-safe log emission.

        Also mirrors into TRANSLATION_RUN_LOG so the LogViewer file-tail shows
        batch/status lines (those never go through translateAI's Input/Output writer).
        """
        self.log_signal.emit(message)
        if isinstance(message, str) and message.startswith("MISMATCH_EVENT:"):
            return
        try:
            run_log = os.getenv("TRANSLATION_RUN_LOG")
            if not run_log or not message:
                return
            text = _strip_ansi(str(message)).rstrip()
            if not text:
                return
            path = Path(run_log)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
                f.flush()
        except Exception:
            pass
        
    def emit_progress(self, current, total, filename):
        """Thread-safe progress emission."""
        self.progress_signal.emit(current, total, filename)
        
    def run_module_in_process(
        self,
        filename,
        estimate_only,
        batch_phase=None,
        file_result_callback=None,
    ):
        """Run a module handler in a separate process for better control."""
        try:
            # Use the external subprocess runner script
            runner_script = self.project_root / "util" / "subprocess_runner.py"
            if not runner_script.exists():
                self.emit_log(f"❌ Subprocess runner script not found: {runner_script}")
                return "Fail"
            
            # Run the script in a separate process
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'  # Force UTF-8 encoding
            if batch_phase in ("collect", "consume"):
                env["BATCH_PHASE"] = batch_phase
                if self.batch_runtime_profile is not None:
                    env["DAZED_BATCH_RUNTIME_PROFILE"] = json.dumps(
                        self.batch_runtime_profile,
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                else:
                    env.pop("DAZED_BATCH_RUNTIME_PROFILE", None)
            else:
                env.pop("BATCH_PHASE", None)
                env.pop("DAZED_BATCH_RUNTIME_PROFILE", None)
            
            multi_file = isinstance(filename, (list, tuple))
            filenames = list(filename) if multi_file else None
            filename_arg = "--files-from-stdin" if multi_file else filename
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(runner_script),
                    str(self.project_root),
                    self.module_info[0],  # module name
                    filename_arg,
                    str(estimate_only)
                ],
                stdin=subprocess.PIPE if multi_file else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(self.project_root),
                env=env,
                bufsize=1  # Line buffered
            )

            if multi_file:
                json.dump(filenames, process.stdin, ensure_ascii=False)
                process.stdin.close()
            
            # Track the process for potential termination
            self.running_processes.append(process)
            
            # Read output in real-time to capture progress
            stdout_lines = []
            stderr_lines = []
            
            def read_stdout():
                """Read stdout line by line."""
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break
                    line = line.strip()
                    if line.startswith('PROGRESS:'):
                        # Parse progress: PROGRESS:filename:current:total
                        try:
                            parts = line.split(':', 3)
                            if len(parts) == 4:
                                _, desc, current, total = parts
                                # Emit with filename included
                                self.item_progress_signal.emit(desc, int(current), int(total))
                        except Exception:
                            pass  # Ignore malformed progress lines
                    elif line.startswith("FILE_RESULT:"):
                        try:
                            payload = json.loads(line[len("FILE_RESULT:"):])
                            if file_result_callback is not None:
                                result = payload.get("result") or "Fail"
                                mismatch_count = int(
                                    payload.get("mismatch_count") or 0
                                )
                                if mismatch_count:
                                    result = (
                                        "VALIDATION_MISMATCH",
                                        "Translation validation failed after all "
                                        "retries; original text was preserved for "
                                        "failed chunks",
                                        result,
                                        mismatch_count,
                                    )
                                file_result_callback(payload["filename"], result)
                        except Exception as exc:
                            stderr_lines.append(
                                f"Invalid multi-file result marker: {exc}"
                            )
                    elif line.startswith("FILE_ERROR:"):
                        try:
                            payload = json.loads(line[len("FILE_ERROR:"):])
                            if file_result_callback is not None:
                                file_result_callback(
                                    payload["filename"],
                                    (
                                        "SUBPROCESS_ERROR",
                                        payload.get("error") or "Unknown error",
                                    ),
                                )
                        except Exception as exc:
                            stderr_lines.append(
                                f"Invalid multi-file error marker: {exc}"
                            )
                    else:
                        stdout_lines.append(line)
                        # Forward each line to the log as it is read, rather than
                        # buffering the whole run and flushing it after the
                        # process exits — a long translation was otherwise a
                        # blank log until it finished. RESULT: is an internal
                        # marker parsed below and is never shown.
                        if line and not line.startswith('RESULT:'):
                            self.emit_log(line)
                process.stdout.close()
            
            def read_stderr():
                """Read stderr line by line."""
                for line in iter(process.stderr.readline, ''):
                    if not line:
                        break
                    stderr_lines.append(line.strip())
                process.stderr.close()
            
            # Start reader threads
            stdout_thread = threading.Thread(target=read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()
            
            # Wait for process completion
            process.wait()
            
            # Wait for reader threads to finish
            stdout_thread.join(timeout=1.0)
            stderr_thread.join(timeout=1.0)
            
            # Combine output
            stdout = '\n'.join(stdout_lines)
            stderr = '\n'.join(stderr_lines)
            
            # Remove from tracking
            if process in self.running_processes:
                self.running_processes.remove(process)
            
            # Check if process was terminated by stop signal
            if self.should_stop:
                return "Stopped"
            
            stdout_lines_clean = stdout.strip().split('\n')
            mismatch_count = sum(
                line.startswith("MISMATCH_EVENT:")
                for line in stdout_lines_clean
            )

            # stdout was already forwarded to the log line by line as it was
            # read (see read_stdout); it is not re-emitted here, only parsed for
            # the RESULT/MISMATCH markers below.

            # Parse result
            if process.returncode == 0:
                result_text = "Success"
                for line in stdout_lines_clean:
                    if line.startswith('RESULT:'):
                        parsed = line[7:]  # Remove 'RESULT:' prefix
                        try:
                            result_text = parsed
                        except UnicodeError:
                            result_text = parsed.encode('ascii', 'ignore').decode('ascii')
                        break
                if mismatch_count:
                    # Soft failure: bad chunks keep source text, valid chunks are
                    # written. Do not fail the whole multi-file run for this.
                    return (
                        "VALIDATION_MISMATCH",
                        "Translation validation failed after all retries; "
                        "original text was preserved for failed chunks",
                        result_text,
                        mismatch_count,
                    )
                return result_text
            else:
                # Extract error message from stderr
                error_msg = stderr.strip() if stderr.strip() else "Unknown error"
                # Handle potential Unicode errors in error messages
                try:
                    clean_error = error_msg.encode('ascii', 'ignore').decode('ascii')
                except:
                    clean_error = "Unicode encoding error in process output"
                
                # Check if stderr contains the actual exception message
                # Format from subprocess_runner.py: "ERROR:actual error message"
                actual_error = clean_error
                for line in clean_error.split('\n'):
                    if line.startswith('ERROR:'):
                        actual_error = line[6:]  # Remove 'ERROR:' prefix
                        break
                    # Check for exception lines in traceback
                    if 'NameError:' in line or 'Error:' in line:
                        # Extract just the error message part
                        if ':' in line:
                            actual_error = line.split(':', 1)[1].strip()
                            break
                
                self.emit_log(f"❌ Process error: {actual_error}")
                # Return the actual error so it can be used to determine if file is unsupported
                return ("SUBPROCESS_ERROR", actual_error)
                
        except Exception as e:
            self.emit_log(f"❌ Failed to run module process: {str(e)}")
            return "Fail"

    def _prepare_mvmz_speakers(self, matching_files, *, emit_progress=False):
        """Scan selected RPG Maker files, then resolve all new speakers together."""
        try:
            import modules.rpgmakermvmz as mvmz
            mvmz.refreshRuntimeConfig()
            if self.batch_runtime_profile is not None:
                from util.runtime_profile import apply_batch_runtime_profile

                apply_batch_runtime_profile(mvmz, self.batch_runtime_profile)
        except Exception as exc:
            self.emit_log(f"❌ Could not start speaker preflight: {exc}")
            return False

        mvmz.resetSpeakerState()
        mvmz.setSpeakerParseMode(True)
        total_files = len(matching_files)
        completed = 0
        scan_failures = []
        try:
            self.status_signal.emit("Scanning speakers…")
            self.emit_log(
                f"🔎 Scanning {total_files} file(s) for unresolved speakers "
                "without making API calls…"
            )
            for filename in matching_files:
                if self.should_stop:
                    return False
                try:
                    mvmz.handleMVMZ(filename, False)
                except Exception as exc:
                    scan_failures.append(filename)
                    tb_line = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                    self.emit_log(
                        f"❌ Error scanning speakers in {filename}: {exc} | Line: {tb_line}"
                    )
                    self.file_error_signal.emit(filename, str(exc))
                completed += 1
                self.status_signal.emit(
                    f"Scanning speakers… {completed}/{total_files}"
                )
                if emit_progress:
                    self.emit_progress(completed, total_files, filename)

            if scan_failures:
                self.emit_log(
                    f"❌ Speaker scan failed for {len(scan_failures)}/{total_files} "
                    "file(s). No speaker translations were submitted."
                )
                return False

            pending = mvmz.pendingSpeakerNames()
            collected_unique = []
            seen_collected = set()
            for name in mvmz.SPEAKER_COLLECTED:
                if not name or name in seen_collected:
                    continue
                seen_collected.add(name)
                collected_unique.append(name)
            covered_count = max(0, len(collected_unique) - len(pending))
            if not pending:
                self.emit_log(
                    f"🔤 Speaker scan complete ({completed}/{total_files}). "
                    f"Detected {len(collected_unique)} unique nameplate(s); "
                    f"all {covered_count} are already covered by the game glossary."
                )
                return True

            self.status_signal.emit(f"Waiting to translate {len(pending)} speakers…")
            self.emit_log(
                f"🔤 Speaker scan complete ({completed}/{total_files}). "
                f"Detected {len(collected_unique)} unique nameplate(s); "
                f"{covered_count} already covered by the glossary; "
                f"{len(pending)} unresolved unique speaker(s). "
                "No speaker API calls have been made."
            )
            from util.skills import ctx
            estimate = self._estimate_grouped_speakers(
                pending, ctx("names.speaker"), mvmz.TRANSLATION_CONFIG, mvmz.MODEL
            )
            self.emit_log(
                f"📊 Speaker estimate: {int(estimate.get('request_count', 0))} grouped request(s), "
                f"{int(estimate.get('input_tokens', 0)):,} input / "
                f"{int(estimate.get('output_tokens', 0)):,} output tokens, approximately "
                f"${float(estimate.get('estimated_cost', 0.0)):.6f}."
            )
            if not self._wait_speaker_translation(pending, estimate):
                self.emit_log(
                    "⏹ Speaker translation canceled. No unresolved speakers were sent, "
                    "and the translation run did not start."
                )
                return False

            self.status_signal.emit(f"Translating {len(pending)} speakers together…")
            self.emit_log(
                f"🔤 Translating {len(pending)} speakers in grouped list batches…"
            )
            before_in, before_out = int(mvmz.TOKENS[0]), int(mvmz.TOKENS[1])
            speakers_saved = mvmz.finalizeSpeakerParse()
            if speakers_saved is False:
                self.emit_log(
                    "❌ Speaker translations could not be validated or saved. "
                    "Check the active game glossary and translation log."
                )
                return False
            delta_in = max(0, int(mvmz.TOKENS[0]) - before_in)
            delta_out = max(0, int(mvmz.TOKENS[1]) - before_out)
            if delta_in or delta_out:
                cost = mvmz.calculateCost(delta_in, delta_out, mvmz.MODEL)
                self.emit_log(
                    f"Speakers: [Input: {delta_in}][Output: {delta_out}]"
                    f"[Cost: ${cost:.4f}] ✓"
                )
            self.emit_log("✅ Speaker translations saved to the game glossary.")
            return True
        finally:
            mvmz.setSpeakerParseMode(False)

    def _prepare_wolf_speakers(self, matching_files):
        """Scan WolfDawn JSON nameplates, then resolve all new speakers together."""
        try:
            import modules.wolfdawn as wolfdawn
            wolfdawn.refreshRuntimeConfig()
        except Exception as exc:
            self.emit_log(f"❌ Could not start WOLF speaker preflight: {exc}")
            return False

        collected = []
        seen = set()
        scan_failures = []
        total_files = len(matching_files)
        self.status_signal.emit("Scanning WOLF speakers…")
        self.emit_log(
            f"🔎 Scanning {total_files} WOLF JSON file(s) for unresolved speakers "
            "without making API calls…"
        )
        for index, filename in enumerate(matching_files, 1):
            if self.should_stop:
                return False
            try:
                path = self.project_root / "files" / filename
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                for speaker in wolfdawn.collectSpeakerNames(data):
                    if speaker not in seen:
                        seen.add(speaker)
                        collected.append(speaker)
            except Exception as exc:
                scan_failures.append(filename)
                self.emit_log(f"❌ Could not scan WOLF speakers in {filename}: {exc}")
                self.file_error_signal.emit(filename, str(exc))
            self.status_signal.emit(
                f"Scanning WOLF speakers… {index}/{total_files}"
            )

        if scan_failures:
            self.emit_log(
                f"❌ WOLF speaker scan failed for {len(scan_failures)}/{total_files} "
                "file(s). No speaker translations were submitted."
            )
            return False

        pending = wolfdawn.pendingSpeakerNames(collected)
        if not pending:
            self.emit_log(
                f"🔤 WOLF speaker scan complete ({total_files}/{total_files}). "
                "Every detected speaker is already in the game glossary."
            )
            return True

        self.status_signal.emit(f"Waiting to translate {len(pending)} speakers…")
        self.emit_log(
            f"🔤 WOLF speaker scan complete. Found {len(pending)} unresolved unique "
            "speaker(s); no speaker API calls have been made."
        )
        from util.skills import ctx
        estimate = self._estimate_grouped_speakers(
            pending, ctx("names.npc"), wolfdawn.TRANSLATION_CONFIG, wolfdawn.MODEL
        )
        self.emit_log(
            f"📊 Speaker estimate: {int(estimate.get('request_count', 0))} grouped request(s), "
            f"{int(estimate.get('input_tokens', 0)):,} input / "
            f"{int(estimate.get('output_tokens', 0)):,} output tokens, approximately "
            f"${float(estimate.get('estimated_cost', 0.0)):.6f}."
        )
        if not self._wait_speaker_translation(pending, estimate):
            self.emit_log(
                "⏹ Speaker translation canceled. No unresolved speakers were sent, "
                "and the translation run did not start."
            )
            return False

        self.status_signal.emit(f"Translating {len(pending)} speakers together…")
        self.emit_log(
            f"🔤 Translating {len(pending)} WOLF speakers in grouped list batches…"
        )
        tokens = wolfdawn.translateSpeakerNames(pending)
        if tokens is False:
            self.emit_log(
                "❌ WOLF speaker translations could not be validated or saved. "
                "The translation run did not start."
            )
            return False
        if tokens[0] or tokens[1]:
            cost = wolfdawn.calculateCost(tokens[0], tokens[1], wolfdawn.MODEL)
            self.emit_log(
                f"Speakers: [Input: {tokens[0]}][Output: {tokens[1]}]"
                f"[Cost: ${cost:.4f}] ✓"
            )
        self.emit_log("✅ Speaker translations saved to the game glossary.")
        return True

    def _run_files(self, matching_files, estimate_only, batch_phase=None):
        """Process matching files; return last cost string or 'Fail'."""
        threads = int(os.getenv("fileThreads", "1"))
        total_cost = "Fail"
        had_failure = False
        module_name_lower = self.module_info[0].lower() if isinstance(self.module_info[0], str) else ""
        is_mvmz = "mv/mz" in module_name_lower

        if self.parse_speakers and is_mvmz:
            prepared = self._prepare_mvmz_speakers(
                matching_files, emit_progress=True
            )
            if not prepared:
                self.should_stop = True
                return "Stopped"
            return "Success"

        completed_count = 0
        total_files = len(matching_files)
        self._run_had_mismatch = False
        self._run_mismatch_count = 0

        def _handle_file_result(filename, result):
            nonlocal total_cost, had_failure, completed_count
            stopped = False
            try:
                if (
                    isinstance(result, tuple)
                    and len(result) >= 2
                    and result[0] == "VALIDATION_MISMATCH"
                ):
                    message = result[1]
                    cost = result[2] if len(result) > 2 else None
                    mismatch_count = max(
                        1, int(result[3] if len(result) > 3 else 1)
                    )
                    self._run_had_mismatch = True
                    self._run_mismatch_count += mismatch_count
                    self.emit_log(
                        f"⚠ {filename}: {_mismatch_summary(mismatch_count)}; "
                        "original text kept for those chunks."
                    )
                    self.file_mismatch_signal.emit(filename, message)
                    if cost and cost not in ("Fail", "Stopped"):
                        total_cost = cost
                    elif total_cost == "Fail":
                        total_cost = "Success"
                elif isinstance(result, tuple) and len(result) == 2 and result[0] == "SUBPROCESS_ERROR":
                    had_failure = True
                    self.file_error_signal.emit(filename, result[1])
                elif result and result not in ("Fail", "Stopped"):
                    total_cost = result
                elif result == "Stopped":
                    stopped = True
                else:
                    had_failure = True
                    self.emit_log(f"❌ Failed processing {filename}")
                    self.file_error_signal.emit(filename, "Translation failed")
            except Exception as e:
                had_failure = True
                tb_line = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                self.emit_log(f"❌ Error processing {filename}: {str(e)} | Line: {tb_line}")
                self.file_error_signal.emit(filename, str(e))
            completed_count += 1
            self.emit_progress(completed_count, total_files, filename)
            return stopped

        # Batch collection and consumption are local, CPU/file-heavy phases.
        # Reuse one imported RPG Maker process for the whole phase instead of
        # paying heavyweight SDK/module startup once per file. Consume remains
        # strictly ordered, preserving glossary harvest semantics.
        if is_mvmz and batch_phase in ("collect", "consume"):
            observed = set()

            def _handle_persistent_result(filename, result):
                observed.add(filename)
                _handle_file_result(filename, result)

            worker_result = self.run_module_in_process(
                list(matching_files),
                estimate_only,
                batch_phase,
                file_result_callback=_handle_persistent_result,
            )
            if self.should_stop:
                return "Stopped"
            if (
                isinstance(worker_result, tuple)
                and worker_result
                and worker_result[0] == "SUBPROCESS_ERROR"
            ):
                for filename in matching_files:
                    if filename not in observed:
                        _handle_file_result(filename, worker_result)
            return "Fail" if had_failure else total_cost

        # Pass 2 is always sequential: each file may harvest names into
        # glossary.txt, and later files need those entries on disk. Paid batch
        # keys still use the collect-time freeze, so these writes are safe.
        if batch_phase == "consume":
            self.executor = None
            for filename in matching_files:
                if self.should_stop:
                    break
                result = self.run_module_in_process(
                    filename, estimate_only, batch_phase
                )
                if _handle_file_result(filename, result):
                    break
            return "Fail" if had_failure else total_cost

        max_workers = 1 if estimate_only else threads
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        future_to_filename = {
            self.executor.submit(
                self.run_module_in_process, filename, estimate_only, batch_phase
            ): filename
            for filename in matching_files
        }

        for future in as_completed(future_to_filename):
            if self.should_stop:
                for remaining_future in future_to_filename:
                    if not remaining_future.done():
                        remaining_future.cancel()
                break

            filename = future_to_filename[future]
            # Resolve the future before emitting progress so cost lines from the
            # subprocess are queued ahead of the file-complete progress event.
            try:
                result = future.result()
            except Exception as e:
                had_failure = True
                tb_line = str(traceback.extract_tb(sys.exc_info()[2])[-1].lineno)
                self.emit_log(f"❌ Error processing {filename}: {str(e)} | Line: {tb_line}")
                self.file_error_signal.emit(filename, str(e))
                completed_count += 1
                self.emit_progress(completed_count, total_files, filename)
                continue
            if _handle_file_result(filename, result):
                break

        if self.executor:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                self.executor.shutdown(wait=False)
            self.executor = None

        return "Fail" if had_failure else total_cost
        
    def run(self):
        """Run the translation process."""
        try:
            load_dotenv()
            sys.path.insert(0, str(self.project_root))

            from util.translation import clear_cache

            if not (self.batch_mode and self.batch_resume_state):
                clear_cache()

            required_envs = ["api", "key", "model", "language", "timeout", "fileThreads", "threads", "width", "listWidth"]
            missing_envs = [
                env for env in required_envs
                if os.getenv(env) is None or str(os.getenv(env))[:1] == "<"
            ]
            if missing_envs:
                names = ", ".join(missing_envs)
                self.emit_log(f"❌ Missing required environment variable(s): {names}")
                self.emit_log("   Check your .env file (see .env.example).")
                self.finished_signal.emit(False, f"Missing env: {names}")
                return

            if self.batch_mode and self.parse_speakers:
                self.emit_log("❌ Batch Translate does not support Parse Speakers mode.")
                self.finished_signal.emit(False, "Batch + Parse Speakers unsupported")
                return

            if self.batch_mode:
                from util.runtime_profile import (
                    capture_batch_runtime_profile,
                    copy_batch_runtime_profile,
                    is_rpgmaker_mvmz,
                )
                from util.translation import batchRunMetadata

                if self.batch_resume_state:
                    saved_profile = batchRunMetadata().get("runtime_profile")
                    if is_rpgmaker_mvmz(self.module_info[0]) and saved_profile is None:
                        self.emit_log(
                            "❌ This RPG Maker batch predates saved runtime profiles. "
                            "Resume was stopped before writing files. Reopen it from the "
                            "guided workflow and confirm the original code profile first."
                        )
                        self.finished_signal.emit(False, "Batch runtime profile missing")
                        return
                    self.batch_runtime_profile = copy_batch_runtime_profile(
                        saved_profile
                    )
                else:
                    self.batch_runtime_profile = capture_batch_runtime_profile(
                        self.module_info[0], self.project_root
                    )

            files_dir = self.project_root / "files"
            if not files_dir.exists():
                self.emit_log("❌ Files directory does not exist!")
                self.finished_signal.emit(False, "Files directory missing")
                return

            if self.selected_files:
                matching_files = self.selected_files
            else:
                matching_files = []
                for file_path in files_dir.iterdir():
                    if file_path.is_file() and file_path.name != '.gitkeep':
                        for ext in self.module_info[1]:
                            if file_path.name.endswith(ext):
                                matching_files.append(file_path.name)
                                break

            if not matching_files:
                self.emit_log(f"❌ No files found matching extensions: {', '.join(self.module_info[1])}")
                self.finished_signal.emit(False, "No matching files")
                return

            self.emit_log(f"📁 Found {len(matching_files)} files to process:")
            for filename in matching_files:
                self.emit_log(f"   • {filename}")
            self.emit_log(f"🔧 Using module: {self.module_info[0]}")
            if self.batch_mode:
                self.emit_log("📦 Batch mode: provider Batch API (typically 50% off)")
            else:
                self.emit_log(f"📊 Estimate only: {'Yes' if self.estimate_only else 'No'}")
            self.emit_log("")

            total_cost = "Fail"
            batch_no_work = False
            old_cwd = os.getcwd()
            os.chdir(str(self.project_root))

            if self.estimate_only:
                try:
                    from util.translation import clear_estimate_written_sizes
                    clear_estimate_written_sizes()
                except Exception:
                    pass

            try:
                should_prepare_speakers = _should_prepare_speakers_automatically(
                    self.module_info[0],
                    estimate_only=self.estimate_only,
                    parse_speakers=self.parse_speakers,
                    batch_mode=self.batch_mode,
                    batch_resume_state=self.batch_resume_state,
                )
                if should_prepare_speakers:
                    module_name_lower = str(self.module_info[0] or "").casefold()
                    if "wolfdawn" in module_name_lower:
                        prepared = self._prepare_wolf_speakers(matching_files)
                    else:
                        prepared = self._prepare_mvmz_speakers(matching_files)
                    if not prepared:
                        self.finished_signal.emit(False, "Speaker translation canceled")
                        return

                if self.batch_mode:
                    from util.translation import (
                        batchQueueStaleContextCount,
                        clearBatchFiles,
                        pendingBatchRequests,
                        estimateBatchCost,
                        saveQueuedBatchMetadata,
                    )

                    if self.batch_resume_state == "queued":
                        stale_requests, queued_requests = batchQueueStaleContextCount()
                        if stale_requests:
                            self.emit_log(
                                f"[BATCH] Glossary or SFX context changed for "
                                f"{stale_requests}/{queued_requests} queued request(s). "
                                "Discarding the stale queue and re-collecting with the "
                                "current translation context."
                            )
                            clearBatchFiles()
                            self.batch_resume_state = None

                    run_consume = True
                    if self.batch_resume_state is None:
                        clearBatchFiles()
                        try:
                            from util.vocab import (
                                freeze_batch_glossary,
                                persist_batch_glossary_freeze_to_state,
                            )

                            freeze_batch_glossary()
                            persist_batch_glossary_freeze_to_state()
                            self.emit_log(
                                "[BATCH] Froze glossary for collect prompts "
                                "(and legacy result rematch if needed)."
                            )
                        except Exception as exc:
                            self.emit_log(
                                f"[BATCH] Could not freeze glossary context: {exc}"
                            )
                        self._emit_batch_phase("collect")
                        self.emit_log("[BATCH] Pass 1/2: collecting requests...")
                        self.emit_log(
                            "[BATCH] Pass 1 queues the main translation requests without "
                            "per-speaker API calls; unresolved speakers were resolved in "
                            "the preflight glossary step when needed."
                        )
                        total_cost = self._run_files(matching_files, False, batch_phase="collect")
                        if self.should_stop:
                            self.finished_signal.emit(False, "Translation stopped")
                            return
                        if total_cost == "Fail":
                            self.emit_log(
                                "[BATCH] Collection failed; submission was blocked so "
                                "no incomplete paid batch can be created."
                            )
                            self.finished_signal.emit(False, "Batch collection failed")
                            return

                        if pendingBatchRequests() == 0:
                            batch_no_work = True
                            self._emit_batch_phase("no_work", {
                                "files": len(matching_files),
                            })
                            self.emit_log(
                                "[BATCH] No eligible untranslated text found. "
                                "No provider batch was submitted."
                            )
                            run_consume = False
                        else:
                            n_requests = pendingBatchRequests()
                            self._emit_batch_phase("collect_done", {
                                "files": len(matching_files),
                                "requests": n_requests,
                            })
                            est = self._emit_batch_output(estimateBatchCost)
                            if est is not None:
                                est = dict(est)
                                est["files"] = len(matching_files)
                            saveQueuedBatchMetadata(
                                matching_files,
                                runtime_profile=self.batch_runtime_profile,
                                workflow_return=self.batch_workflow_return,
                            )
                            if not self._wait_batch_submit(est):
                                self._emit_batch_phase("canceled", est)
                                self.emit_log(
                                    "[BATCH] Canceled. The local queue was discarded and "
                                    "nothing was sent to the provider."
                                )
                                self.finished_signal.emit(True, "Batch canceled")
                                return
                            poll_result = self._run_batch_poll_fetch()
                            if poll_result is None:
                                self.finished_signal.emit(False, "Batch polling stopped")
                                return
                    elif self.batch_resume_state == "queued":
                        # Resume a declined/interrupted collect: estimate + submit only.
                        self.emit_log(
                            "[BATCH] Resuming queued requests (skipping re-collect to avoid "
                            "duplicate live charges and a second batch submission)..."
                        )
                        n_requests = pendingBatchRequests()
                        if n_requests == 0:
                            batch_no_work = True
                            self._emit_batch_phase("no_work", {
                                "files": len(matching_files),
                            })
                            self.emit_log(
                                "[BATCH] Queue is empty. No provider batch was submitted."
                            )
                            run_consume = False
                        else:
                            self._emit_batch_phase("collect_done", {
                                "files": len(matching_files),
                                "requests": n_requests,
                            })
                            est = self._emit_batch_output(estimateBatchCost)
                            if est is not None:
                                est = dict(est)
                                est["files"] = len(matching_files)
                            if not self._wait_batch_submit(est):
                                self._emit_batch_phase("canceled", est)
                                self.emit_log(
                                    "[BATCH] Canceled. The local queue was discarded and "
                                    "nothing was sent to the provider."
                                )
                                self.finished_signal.emit(True, "Batch canceled")
                                return
                            poll_result = self._run_batch_poll_fetch()
                            if poll_result is None:
                                self.finished_signal.emit(False, "Batch polling stopped")
                                return
                    elif self.batch_resume_state in {"submitted", "partially_submitted"}:
                        self._emit_batch_phase("polling")
                        self.emit_log(
                            "[BATCH] Resuming submitted batch..."
                            if self.batch_resume_state == "submitted"
                            else "[BATCH] Resuming partially submitted split batch..."
                        )
                        poll_result = self._run_batch_poll_fetch()
                        if poll_result is None:
                            self.finished_signal.emit(False, "Batch polling stopped")
                            return
                    else:
                        self.emit_log("[BATCH] Resuming from fetched results...")
                        try:
                            from util.vocab import BATCH_GLOSSARY_FREEZE_FILE

                            if not BATCH_GLOSSARY_FREEZE_FILE.is_file():
                                self.emit_log(
                                    "[BATCH] NOTE: no collect-time glossary freeze on disk. "
                                    "v5+ batch keys ignore glossary/SFX; freeze is only needed "
                                    "to rematch older (pre-v5) paid results."
                                )
                        except Exception:
                            pass

                    if run_consume and not self.should_stop:
                        try:
                            from util.batch_history import missing_result_count
                            present, expected = missing_result_count()
                            if expected and present < expected:
                                self.emit_log(
                                    f"[BATCH] WARNING: only {present}/{expected} results present. "
                                    "The consume pass will stop on a missing key; it will not "
                                    "make a full-price live request."
                                )
                        except Exception:
                            pass
                        self._emit_batch_phase("consume")
                        self.emit_log("[BATCH] Pass 2/2: writing translated files...")
                        self.emit_log(
                            "[BATCH] Pass 2 runs one file at a time so glossary "
                            "harvests from earlier files are available to later ones."
                        )
                        try:
                            from util.vocab import restore_batch_glossary_freeze_from_state

                            if restore_batch_glossary_freeze_from_state():
                                self.emit_log(
                                    "[BATCH] Restored collect-time glossary freeze."
                                )
                        except Exception:
                            pass
                        total_cost = self._run_files(matching_files, False, batch_phase="consume")
                else:
                    total_cost = self._run_files(matching_files, self.estimate_only)
            finally:
                os.chdir(old_cwd)
                
            # Clean up temporary files
            tmp_file = self.project_root / "csv.tmp"
            if tmp_file.exists():
                tmp_file.unlink()
                
            # Clean up any remaining temporary scripts
            temp_script = self.project_root / "temp_translation_script.py"
            if temp_script.exists():
                temp_script.unlink()
                
            # Ensure all processes are terminated
            if self.running_processes:
                for process in self.running_processes:
                    try:
                        if process.poll() is None:
                            process.terminate()
                            process.wait(timeout=1)
                    except:
                        pass
                self.running_processes.clear()
                
            # Report results
            if total_cost != "Fail" and not self.should_stop:
                if self.batch_mode:
                    try:
                        from util.translation import clearBatchFiles
                        clearBatchFiles(strict=True)
                    except Exception as exc:
                        self.emit_log(
                            "⚠ Batch output was written, but completed-batch recovery "
                            f"files could not be cleared: {exc}"
                        )
                    if not batch_no_work:
                        self._emit_batch_phase(
                            "done",
                            {
                                "mismatches": getattr(
                                    self, "_run_mismatch_count", 0
                                )
                            },
                        )
                self.emit_log("")
                self.emit_log(f"💰 {total_cost}")
                if self.batch_mode and batch_no_work:
                    self.emit_log("ℹ️ Batch scan completed with no work to submit.")
                elif self.batch_mode:
                    self.emit_log("✅ Batch translation completed!")
                elif not self.estimate_only:
                    self.emit_log("✅ Translation completed successfully!")
                else:
                    self.emit_log("✅ Estimation completed!")
                    try:
                        from util.translation import clear_estimate_written_sizes
                        clear_estimate_written_sizes()
                    except Exception:
                        pass
                if getattr(self, "_run_had_mismatch", False):
                    self.emit_log(
                        f"⚠ Completed with {_mismatch_summary(getattr(self, '_run_mismatch_count', 0))}; "
                        "original text was kept for those chunks. Review Issues in "
                        "the translation log."
                    )
                self.finished_signal.emit(True, str(total_cost))
            else:
                if not self.should_stop:
                    self.emit_log("❌ Translation failed!")
                    self.finished_signal.emit(False, "Translation failed")
                else:
                    # Only log the final stop message here
                    self.emit_log("🛑 Translation stopped by user")
                    self.finished_signal.emit(False, "Translation stopped")
                    
        except Exception as e:
            error_msg = f"❌ Unexpected error: {str(e)}"
            self.emit_log(error_msg)
            self.finished_signal.emit(False, error_msg)


class TranslationTab(QWidget):
    """Simple translation tab with file management and console log.

    Emits engine_changed(str) when the selected module implies a different
    engine configuration tab should be displayed.
    """
    engine_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        # Persistent settings (remember last directory used in file dialogs)
        try:
            self.settings = QSettings(ORG_NAME, APP_NAME)
        except Exception:
            self.settings = None
        # If the worker signals finished before all file progress updates
        # have been received, we queue the finalization until the last
        # file progress update arrives.
        self._finish_pending = None
        self.translation_process = None
        self.log_buffer = []  # Buffer for batching log messages
        self.log_timer = QTimer()  # Timer for flushing log buffer
        self.log_timer.timeout.connect(self.flush_log_buffer)
        
        # Set up directories
        self.project_root = Path(__file__).parent.parent
        self.files_dir = self.project_root / "files"
        self.translated_dir = self.project_root / "translated"
        
        # Ensure directories exist
        self.files_dir.mkdir(exist_ok=True)
        self.translated_dir.mkdir(exist_ok=True)
        
        # Initialize tracking variables
        self.files_completed = 0
        self.files_total = 0
        self._file_progress_started = False
        self.file_progress_items = {}  # filename -> {widget, label, progress_bar, checkbox}
        self.current_translating_file = None
        # Totals tracking
        self.totals_input_tokens = 0
        self.totals_output_tokens = 0
        self.totals_cost = 0.0
        self.totals_time = 0.0
        # Track which filenames' totals have been applied (prevents double-counting)
        self._applied_file_totals = set()
        # Filenames from the most recently completed translation run (used by post-run export)
        self._last_run_files: list = []
        # Workflow pages register themselves before opening Translation. The
        # pending target is consumed only when a run actually starts so a
        # failed preflight does not lose the return path.
        self._pending_workflow_return = None
        self._active_workflow_return = None
        # Totals widget reference
        self.totals_widget = None
        self._batch_active = False
        self._batch_ui_phase = None
        self._batch_consume_started = False
        self._batch_tab_index = -1
        self._mode_user_selected = False
        self._last_default_translation_mode = None
        
        self.setup_ui()
        self.setup_module_list()
        self.refresh_file_lists()
        
    def setup_ui(self):
        """Set up the user interface."""
        # Create a fixed horizontal layout to separate translation controls from log viewer.
        # Using a layout instead of QSplitter prevents the user from resizing panes.
        main_container = QWidget()
        main_hbox = QHBoxLayout()
        # Match left side padding so headers align at the top of the boxes
        main_hbox.setContentsMargins(0, 0, 0, 0)
        main_hbox.setSpacing(Spacing.MD)
    # Align child widgets individually when needed; avoid setting a
    # global AlignTop on the HBox so children with Expanding size
    # policies can grow vertically to fill available space.

        # Left side - translation controls
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(Spacing.MD)
        setup_card = SectionCard("Translation settings", compact=True)
        self.setup_card = setup_card
        setup_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        left_layout.addWidget(setup_card)

        file_card = SectionCard("Files to translate", compact=True)
        self.file_card = file_card
        file_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(file_card, 1)
        layout = file_card.content_layout

        # Create stacked widget to switch between file list and progress view
        self.file_stack = QStackedWidget()
        self.file_stack.setObjectName("translationWorkStack")
        self.file_stack.setStyleSheet(
            "QStackedWidget#translationWorkStack { background-color: transparent; }"
        )
        
        # Page 0: Normal file list with buttons
        file_list_page = QWidget()
        file_list_page.setObjectName("translationFilePage")
        file_list_page.setStyleSheet(
            "#translationFilePage { background-color: transparent; }"
        )
        file_list_layout = QVBoxLayout()
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        
        # Files Section with side buttons
        files_container = QHBoxLayout()
        files_container.setSpacing(Spacing.SM)
        
        # File list with checkboxes
        self.file_list = CheckableFileList()
        # Allow the file list to expand vertically to fill available space
        # (remove fixed minimum height so it can stretch).
        self.file_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # No max height - let it expand
        self.file_list.setStyleSheet("""
            QListWidget {
                outline: none;
                border: 1px solid #555555;
            }
            QListWidget::item {
                border: none;
                outline: none;
            }
            QListWidget::item:hover {
                background-color: #3e3e42;
            }
            QListWidget::item:selected {
                background-color: #264f78;
                color: #ffffff;
            }
        """)
        self.file_list.itemChanged.connect(self._update_selection_summary)

        # File actions use readable labels; icons supplement rather than replace meaning.
        _icon_size = QSize(18, 18)

        def _file_button(text, glyph, tooltip, slot, *, variant="secondary"):
            btn = QPushButton(text)
            qt_icons.apply_button_icon(btn, f"{glyph} {text}", color="#dddddd")
            btn.setIconSize(_icon_size)
            configure_action_button(btn, variant=variant, tooltip=tooltip)
            btn.clicked.connect(slot)
            return btn

        self.selection_summary_label = QLabel("No files available")
        self.selection_summary_label.setObjectName("appStatusText")
        self.selection_summary_label.setWordWrap(True)

        self.select_all_button = _file_button(
            "Select all", "✓", "Select every visible file", self.select_all_files
        )
        self.clear_selection_button = _file_button(
            "Clear", "✗", "Clear the current file selection", self.deselect_all_files,
            variant="quiet",
        )
        self.add_files_button = _file_button(
            "Add files…", "➕", "Copy files into the translation workspace", self.add_input_files
        )
        self.remove_files_button = _file_button(
            "Remove selected", "🗑", "Delete selected files from the workspace",
            self.remove_selected_files, variant="danger",
        )
        more_menu = QMenu(self)
        self.open_files_action = more_menu.addAction(
            "Open workspace folder", self.open_input_folder
        )
        more_menu.addAction("Refresh file list", self.refresh_file_lists)
        self.sidebar_export_action = more_menu.addAction(
            "Export selected translations to game", self._export_selected_files
        )
        more_menu.addAction("Check model pricing", self._check_model_pricing)
        self.more_file_actions_button = QPushButton("More…")
        configure_action_button(
            self.more_file_actions_button,
            variant="quiet",
            tooltip="Refresh files, export selected translations, or check model pricing",
        )
        self.more_file_actions_button.setMenu(more_menu)

        file_toolbar = QWidget()
        file_toolbar.setObjectName("translationFileToolbar")
        file_toolbar.setStyleSheet(
            "#translationFileToolbar, #translationFileToolbarTop, "
            "#translationFileToolbarBottom { background: transparent; border: none; }"
        )
        file_toolbar.setMinimumHeight(Geometry.CONTROL)
        self.file_toolbar = file_toolbar
        file_controls_layout = QVBoxLayout(file_toolbar)
        file_controls_layout.setContentsMargins(0, 0, 0, 0)
        file_controls_layout.setSpacing(Spacing.SM)
        self.file_controls_layout = file_controls_layout

        self.file_controls_top_host = QWidget(file_toolbar)
        self.file_controls_top_host.setObjectName("translationFileToolbarTop")
        self.file_controls_top_layout = QHBoxLayout(self.file_controls_top_host)
        self.file_controls_top_layout.setContentsMargins(0, 0, 0, 0)
        self.file_controls_top_layout.setSpacing(Spacing.SM)
        file_controls_layout.addWidget(self.file_controls_top_host)

        self.file_controls_bottom_host = QWidget(file_toolbar)
        self.file_controls_bottom_host.setObjectName("translationFileToolbarBottom")
        self.file_controls_bottom_layout = QHBoxLayout(self.file_controls_bottom_host)
        self.file_controls_bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.file_controls_bottom_layout.setSpacing(Spacing.SM)
        file_controls_layout.addWidget(self.file_controls_bottom_host)
        self._file_controls_layout_mode = None
        file_list_layout.addWidget(file_toolbar)
        self._arrange_translation_file_controls()
        files_container.addWidget(self.file_list)

        # (Totals footer will be created below and shown only when translation starts)

        # Add the container to file list page and allow it to expand so
        # the file list can grow and push settings to the bottom.
        file_list_layout.addLayout(files_container, 1)
        # (Totals footer removed here; totals will be shown next to the
        # back/open buttons in the progress view as requested.)
        file_list_page.setLayout(file_list_layout)
        self.file_stack.addWidget(file_list_page)  # Index 0
        
        # Page 1: Progress view (shown during translation)
        progress_view_page = QWidget()
        progress_view_page.setObjectName("translationProgressPage")
        progress_view_page.setStyleSheet(
            "#translationProgressPage { background-color: transparent; }"
        )
        progress_view_layout = QVBoxLayout()
        progress_view_layout.setContentsMargins(0, 0, 0, 0)
        progress_view_layout.setSpacing(8)

        # Batch pipeline panel (shown only during batch runs)
        self.batch_pipeline_widget = QWidget()
        self.batch_pipeline_widget.setVisible(False)
        batch_pipe_layout = QVBoxLayout()
        batch_pipe_layout.setContentsMargins(12, 12, 12, 12)
        batch_pipe_layout.setSpacing(Spacing.MD)

        self.batch_phase_title = QLabel("Batch Translate")
        self.batch_phase_title.setStyleSheet("color:#4ec9b0;font-weight:bold;font-size:13px;")
        batch_pipe_layout.addWidget(self.batch_phase_title)

        # Step strip: Collect → Submit → Process → Write
        self.batch_steps_row = QHBoxLayout()
        self.batch_steps_row.setSpacing(Spacing.SM)
        self._batch_step_labels = []
        for i, name in enumerate(("1. Collect", "2. Submit", "3. Process", "4. Write")):
            lab = QLabel(name)
            lab.setAlignment(Qt.AlignCenter)
            lab.setStyleSheet(self._batch_step_style("idle"))
            self.batch_steps_row.addWidget(lab, 1)
            self._batch_step_labels.append(lab)
            if i < 3:
                arrow = QLabel("→")
                arrow.setStyleSheet("color:#666666;font-size:12px;")
                arrow.setAlignment(Qt.AlignCenter)
                self.batch_steps_row.addWidget(arrow, 0)
        batch_pipe_layout.addLayout(self.batch_steps_row)

        self.batch_overall_bar = QProgressBar()
        self.batch_overall_bar.setRange(0, 100)
        self.batch_overall_bar.setValue(0)
        self.batch_overall_bar.setFixedHeight(20)
        self.batch_overall_bar.setTextVisible(True)
        self.batch_overall_bar.setFormat("%p%")
        self.batch_overall_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 3px;
                text-align: center;
                background-color: #2b2b2b;
                color: #cccccc;
            }
            QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 3px;
            }
        """)
        batch_pipe_layout.addWidget(self.batch_overall_bar)

        self.batch_pipeline_stack = QStackedWidget()

        collect_page = QWidget()
        collect_layout = QVBoxLayout(collect_page)
        collect_layout.setContentsMargins(0, 0, 0, 0)
        collect_layout.setSpacing(8)
        self.batch_collect_warning = QLabel(BATCH_COLLECT_LIVE_CHARGE_NOTE)
        self.batch_collect_warning.setWordWrap(True)
        self.batch_collect_warning.setStyleSheet("color:#f0ad4e;font-size:11px;")
        collect_layout.addWidget(self.batch_collect_warning)
        self.batch_collect_status = QLabel("Pass 1/2: collecting API requests from selected files…")
        self.batch_collect_status.setWordWrap(True)
        self.batch_collect_status.setStyleSheet("color:#cccccc;font-size:12px;")
        collect_layout.addWidget(self.batch_collect_status)
        self.batch_pipeline_stack.addWidget(collect_page)

        submit_page = QWidget()
        submit_layout = QVBoxLayout(submit_page)
        submit_layout.setContentsMargins(0, 0, 0, 0)
        submit_layout.setSpacing(8)
        self.batch_submit_summary = QLabel("")
        self.batch_submit_summary.setWordWrap(True)
        self.batch_submit_summary.setAlignment(Qt.AlignTop)
        self.batch_submit_summary.setStyleSheet("color:#cccccc;font-size:12px;")
        submit_layout.addWidget(self.batch_submit_summary)
        # Cost chips row
        self.batch_cost_row = QHBoxLayout()
        self.batch_cost_row.setSpacing(8)
        self.batch_cost_cached = QLabel("Batch+cache: —")
        self.batch_cost_nocache = QLabel("Batch worst: —")
        self.batch_cost_live = QLabel("Live: —")
        for lab in (self.batch_cost_cached, self.batch_cost_nocache, self.batch_cost_live):
            lab.setStyleSheet(
                "color:#cccccc;background:#1e1e1e;border:1px solid #3e3e42;"
                "border-radius:4px;padding:8px;font-size:12px;"
            )
            lab.setAlignment(Qt.AlignCenter)
            self.batch_cost_row.addWidget(lab, 1)
        submit_layout.addLayout(self.batch_cost_row)
        submit_btn_row = QHBoxLayout()
        submit_btn_row.addStretch()
        self.batch_submit_yes_btn = QPushButton("Submit Batch")
        self.batch_submit_yes_btn.setStyleSheet(
            "QPushButton{background-color:#007acc;color:white;font-weight:bold;padding:6px 16px;border-radius:4px;}"
            "QPushButton:hover{background-color:#106ebe;}"
        )
        self.batch_submit_yes_btn.clicked.connect(self._on_batch_submit_yes)
        self.batch_submit_no_btn = QPushButton("Cancel")
        self.batch_submit_no_btn.setStyleSheet(
            "QPushButton{background-color:#555;color:white;padding:6px 16px;border-radius:4px;}"
            "QPushButton:hover{background-color:#666;}"
        )
        self.batch_submit_no_btn.clicked.connect(self._on_batch_submit_no)
        submit_btn_row.addWidget(self.batch_submit_no_btn)
        submit_btn_row.addWidget(self.batch_submit_yes_btn)
        submit_layout.addLayout(submit_btn_row)
        submit_layout.addStretch(1)
        self.batch_pipeline_stack.addWidget(submit_page)

        poll_page = QWidget()
        poll_layout = QVBoxLayout(poll_page)
        poll_layout.setContentsMargins(0, 0, 0, 0)
        poll_layout.setSpacing(8)
        self.batch_poll_id = QLabel("Batch: —")
        self.batch_poll_id.setStyleSheet("color:#9cdcfe;font-size:12px;font-family:monospace;")
        self.batch_poll_id.setTextInteractionFlags(Qt.TextSelectableByMouse)
        poll_layout.addWidget(self.batch_poll_id)
        self.batch_poll_status = QLabel("Waiting for the provider to finish processing the batch…")
        self.batch_poll_status.setWordWrap(True)
        self.batch_poll_status.setStyleSheet("color:#cccccc;font-size:12px;")
        poll_layout.addWidget(self.batch_poll_status)
        # Request count chips
        self.batch_count_row = QHBoxLayout()
        self.batch_count_row.setSpacing(Spacing.SM)
        self._batch_count_labels = {}
        for key, color in (
            ("succeeded", "#4ec9b0"),
            ("processing", "#007acc"),
            ("errored", "#f44747"),
            ("canceled", "#ce9178"),
            ("expired", "#dcdcaa"),
        ):
            lab = QLabel(f"{key}: 0")
            lab.setAlignment(Qt.AlignCenter)
            lab.setStyleSheet(
                f"color:{color};background:#1e1e1e;border:1px solid #3e3e42;"
                f"border-radius:4px;padding:6px 4px;font-size:11px;font-weight:bold;"
            )
            self.batch_count_row.addWidget(lab, 1)
            self._batch_count_labels[key] = lab
        poll_layout.addLayout(self.batch_count_row)
        self.batch_poll_bar = QProgressBar()
        self.batch_poll_bar.setRange(0, 100)
        self.batch_poll_bar.setValue(0)
        self.batch_poll_bar.setFixedHeight(16)
        self.batch_poll_bar.setTextVisible(True)
        self.batch_poll_bar.setFormat("Requests complete: %v / %m")
        self.batch_poll_bar.setStyleSheet("""
            QProgressBar { border: none; background-color: #2b2b2b; border-radius: 3px; color:#ccc; text-align:center; }
            QProgressBar::chunk { background-color: #4ec9b0; border-radius: 3px; }
        """)
        poll_layout.addWidget(self.batch_poll_bar)
        self.batch_poll_hint = QLabel("Stop is safe - the batch keeps running at the provider. Resume later from Batches or Batch Translate.")
        self.batch_poll_hint.setWordWrap(True)
        self.batch_poll_hint.setStyleSheet("color:#888888;font-size:11px;")
        poll_layout.addWidget(self.batch_poll_hint)
        poll_layout.addStretch(1)
        self.batch_pipeline_stack.addWidget(poll_page)

        consume_page = QWidget()
        consume_layout = QVBoxLayout(consume_page)
        consume_layout.setContentsMargins(0, 0, 0, 0)
        consume_layout.setSpacing(8)
        self.batch_consume_status = QLabel("Pass 2/2: writing translated files from batch results…")
        self.batch_consume_status.setWordWrap(True)
        self.batch_consume_status.setStyleSheet("color:#cccccc;font-size:12px;")
        consume_layout.addWidget(self.batch_consume_status)
        self.batch_consume_hint = QLabel("Watch the Translation Log for [BATCH]/[CACHE] Input/Output pairs as each chunk is applied.")
        self.batch_consume_hint.setWordWrap(True)
        self.batch_consume_hint.setStyleSheet("color:#888888;font-size:11px;")
        consume_layout.addWidget(self.batch_consume_hint)
        consume_layout.addStretch(1)
        self.batch_pipeline_stack.addWidget(consume_page)

        batch_pipe_layout.addWidget(self.batch_pipeline_stack, 1)
        self.batch_live_status = QLabel("")
        self.batch_live_status.setWordWrap(True)
        self.batch_live_status.setStyleSheet("color:#666666;font-size:11px;")
        batch_pipe_layout.addWidget(self.batch_live_status)

        self.batch_pipeline_widget.setLayout(batch_pipe_layout)
        self.batch_pipeline_widget.setObjectName("batchPipeline")
        self.batch_pipeline_widget.setStyleSheet("""
            #batchPipeline {
                background-color: #252526;
                border: 1px solid #3e3e42;
                border-radius: 4px;
            }
        """)
        self.batch_pipeline_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.batch_pipeline_stack.setStyleSheet("background: transparent;")
        self.batch_pipeline_stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        # Prefer a Batch-history-style table for per-file status. Keep a hidden,
        # parented list as a compatibility shim so clear()/legacy refs stay safe
        # without creating an orphan top-level window (minimize/restore glitches).
        self.progress_list = QListWidget(self)
        self.progress_list.setVisible(False)
        self.progress_list.setMaximumSize(0, 0)

        self.progress_files_summary = QLabel("No files in this run.")
        self.progress_files_summary.setStyleSheet("color:#9d9d9d;font-size:12px;padding:2px 0;")

        self.progress_table = QTableWidget(0, 6)
        self.progress_table.setHorizontalHeaderLabels(
            ["File", "Status", "Progress", "Tokens", "Cost", "Time"]
        )
        self.progress_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.progress_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.progress_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.progress_table.setAlternatingRowColors(True)
        self.progress_table.verticalHeader().setVisible(False)
        self.progress_table.setShowGrid(True)
        self.progress_table.setStyleSheet(
            "QTableWidget{background-color:#1e1e1e;color:#cccccc;gridline-color:#3a3a3a;"
            "alternate-background-color:#252526;border:1px solid #555555;}"
            "QHeaderView::section{background-color:#2d2d30;color:#cccccc;padding:4px;"
            "border:1px solid #3a3a3a;font-weight:bold;}"
        )
        hdr = self.progress_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 6):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.progress_table.verticalHeader().setDefaultSectionSize(28)

        self.progress_overview_page = QWidget()
        overview_layout = QVBoxLayout(self.progress_overview_page)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(0)
        overview_layout.addWidget(self.batch_pipeline_widget, 1)

        self.progress_files_page = QWidget()
        files_page_layout = QVBoxLayout(self.progress_files_page)
        files_page_layout.setContentsMargins(0, 0, 0, 0)
        files_page_layout.setSpacing(8)
        files_page_layout.addWidget(self.progress_files_summary)
        files_page_layout.addWidget(self.progress_table, 1)

        self.progress_tab_row = QWidget()
        self.progress_tab_row.setObjectName("translationProgressTabs")
        self.progress_tab_row.setStyleSheet(
            "#translationProgressTabs { background-color: transparent; }"
        )
        progress_tab_row_layout = QHBoxLayout(self.progress_tab_row)
        progress_tab_row_layout.setContentsMargins(0, 0, 0, 0)
        progress_tab_row_layout.setSpacing(Spacing.SM)
        self.batch_tab_btn = QPushButton("Batch")
        self.batch_tab_btn.setObjectName("appSubnavButton")
        self.batch_tab_btn.setCheckable(True)
        self.batch_tab_btn.setAutoExclusive(True)
        self.batch_tab_btn.setMinimumSize(144, Geometry.CONTROL)
        self.batch_tab_btn.setCursor(Qt.PointingHandCursor)
        self.batch_tab_btn.clicked.connect(lambda: self._switch_progress_tab(0))
        self.files_tab_btn = QPushButton("Files")
        self.files_tab_btn.setObjectName("appSubnavButton")
        self.files_tab_btn.setCheckable(True)
        self.files_tab_btn.setAutoExclusive(True)
        self.files_tab_btn.setMinimumSize(144, Geometry.CONTROL)
        self.files_tab_btn.setCursor(Qt.PointingHandCursor)
        self.files_tab_btn.clicked.connect(lambda: self._switch_progress_tab(1))
        progress_tab_row_layout.addWidget(self.batch_tab_btn)
        progress_tab_row_layout.addWidget(self.files_tab_btn)
        progress_tab_row_layout.addStretch()
        self.progress_tab_row.setVisible(False)

        self.progress_content_stack = QStackedWidget()
        self.progress_content_stack.addWidget(self.progress_overview_page)
        self.progress_content_stack.addWidget(self.progress_files_page)
        self.progress_content_stack.setCurrentIndex(1)
        self.progress_content_stack.setSizePolicy(
            QSizePolicy.Ignored, QSizePolicy.Expanding
        )

        progress_view_layout.addWidget(self.progress_tab_row)
        progress_view_layout.addWidget(self.progress_content_stack, 1)

        # Run actions remain readable in every state. Icons reinforce the labels
        # but never carry the meaning on their own.
        self.reset_view_button = QPushButton("Back to files")
        qt_icons.apply_button_icon(
            self.reset_view_button, "← Back to files", color="#dddddd"
        )
        self.reset_view_button.setToolTip("Return to the file selection")
        self.reset_view_button.clicked.connect(self.reset_to_file_view)
        self.reset_view_button.setVisible(False)
        configure_action_button(self.reset_view_button, variant="quiet")

        self.return_to_workflow_button = QPushButton("Return to workflow")
        qt_icons.apply_button_icon(
            self.return_to_workflow_button, "← Return to workflow", color="#ffffff"
        )
        self.return_to_workflow_button.setToolTip(
            "Return to the workflow step that started this translation"
        )
        self.return_to_workflow_button.clicked.connect(self._return_to_workflow)
        self.return_to_workflow_button.setVisible(False)
        configure_action_button(self.return_to_workflow_button, variant="primary")

        self.open_translations_button = QPushButton("Open output folder")
        qt_icons.apply_button_icon(
            self.open_translations_button, "📂 Open output folder", color="#dddddd"
        )
        self.open_translations_button.setToolTip("Open the translated files folder")
        self.open_translations_button.clicked.connect(self.open_output_folder)
        self.open_translations_button.setVisible(False)
        configure_action_button(self.open_translations_button, variant="secondary")

        # Keep the workspace and game export in one post-run action. These two
        # destinations represent the same accepted translation state and should
        # not be allowed to drift because the user noticed only one button.
        self.sync_export_button = QPushButton("Sync/Export")
        qt_icons.apply_button_icon(
            self.sync_export_button, "📤 Sync/Export", color="#ffffff"
        )
        self.sync_export_button.setToolTip(
            "Copy this run's translated files into both the workspace and the game folder"
        )
        self.sync_export_button.clicked.connect(self._sync_and_export_last_run_files)
        self.sync_export_button.setVisible(False)
        configure_action_button(self.sync_export_button, variant="primary")

        # Stop is the only destructive run action, so it keeps the danger role.
        self.stop_button = QPushButton("Stop run")
        qt_icons.apply_button_icon(self.stop_button, "🛑 Stop run", color="#ffffff")
        self.stop_button.setToolTip("Stop the current translation run")
        self.stop_button.clicked.connect(self.stop_translation)
        configure_action_button(self.stop_button, variant="danger")
        self.stop_button.setIconSize(QSize(20, 20))
        self.stop_button.setVisible(False)

        # Keep run metrics in their own full-width strip so they never compete
        # with result actions for horizontal space.
        buttons_container = QWidget()
        buttons_container.setObjectName("translationRunFooter")
        buttons_container.setStyleSheet(
            "QWidget#translationRunFooter { background: transparent; border: none; }"
        )
        self.run_footer = buttons_container
        buttons_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        footer_layout = QVBoxLayout(buttons_container)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(Spacing.SM)

        actions_host = QWidget()
        actions_host.setObjectName("translationRunActions")
        actions_host.setStyleSheet(
            "QWidget#translationRunActions { background: transparent; border: none; }"
        )
        self.run_actions_host = actions_host
        buttons_hbox = QHBoxLayout()
        buttons_hbox.setContentsMargins(0, 0, 0, 0)
        buttons_hbox.setSpacing(Spacing.SM)
        # Back/Open/Stop buttons on the left (stop shown while running)
        buttons_hbox.addWidget(self.stop_button)
        buttons_hbox.addWidget(self.return_to_workflow_button)
        buttons_hbox.addWidget(self.reset_view_button)
        buttons_hbox.addWidget(self.open_translations_button)
        buttons_hbox.addWidget(self.sync_export_button)
        buttons_hbox.addStretch()
        actions_host.setLayout(buttons_hbox)

        # Run summary strip (hidden until a run starts)
        self.totals_widget = QWidget()
        self.totals_widget.setObjectName("translationRunSummary")
        self.totals_widget.setStyleSheet(
            f"QWidget#translationRunSummary {{ background:{COLORS.surface_2};"
            f"border:1px solid {COLORS.border};"
            f"border-radius:{Geometry.RADIUS_CONTROL}px; }}"
        )
        self.totals_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        totals_layout = QVBoxLayout(self.totals_widget)
        totals_layout.setContentsMargins(
            Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM
        )
        totals_layout.setSpacing(Spacing.XS)
        metrics_row = QHBoxLayout()
        metrics_row.setContentsMargins(0, 0, 0, 0)
        metrics_row.setSpacing(Spacing.XL)
        self.totals_tokens_label = QLabel("Tokens: 0 in / 0 out")
        self.totals_tokens_label.setStyleSheet("color: #f1c40f; font-weight: bold;")
        self.totals_tokens_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.totals_tokens_label.setWordWrap(True)
        metrics_row.addWidget(self.totals_tokens_label)
        self.totals_cost_label = QLabel("Cost: $0.0000")
        self.totals_cost_label.setStyleSheet("color: #4ec9b0; font-weight: bold;")
        self.totals_cost_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.totals_cost_label.setWordWrap(True)
        metrics_row.addWidget(self.totals_cost_label)
        self.totals_time_label = QLabel("Time: 0.0s")
        self.totals_time_label.setStyleSheet("color: #4da6ff; font-weight: bold;")
        self.totals_time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.totals_time_label.setWordWrap(False)
        metrics_row.addWidget(self.totals_time_label)
        metrics_row.addStretch()
        totals_layout.addLayout(metrics_row)
        self.totals_mismatch_label = QLabel("")
        self.totals_mismatch_label.setStyleSheet("color: #d4a017; font-weight: bold;")
        self.totals_mismatch_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.totals_mismatch_label.setWordWrap(True)
        self.totals_mismatch_label.setVisible(False)
        totals_layout.addWidget(self.totals_mismatch_label)
        self.totals_widget.setVisible(False)
        footer_layout.addWidget(self.totals_widget)
        footer_layout.addWidget(actions_host)
        progress_view_layout.addWidget(buttons_container)
        
        progress_view_page.setLayout(progress_view_layout)
        self.file_stack.addWidget(progress_view_page)  # Index 1
        
        # Add stacked widget to main layout and allow it to stretch
        # so the input files area can take up available vertical space.
        layout.addWidget(self.file_stack, 1)
            
        # Progress Section (removed from UI)
        # The visible progress UI was removed per user request. We keep the
        # underlying widgets as attributes so existing logic can update them
        # without raising AttributeError, but we do not add them to the
        # layout so they are not shown.
        
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(8)
        progress_layout.setContentsMargins(0, 0, 0, 12)
        
        # Files Translated counter
        files_layout = QHBoxLayout()
        files_layout.addWidget(QLabel("Files Translated:"))
        self.files_translated_label = QLabel("0/0")
        self.files_translated_label.setStyleSheet("font-weight: bold; color: #007acc;")
        files_layout.addWidget(self.files_translated_label)
        files_layout.addStretch()
        progress_layout.addLayout(files_layout)
        
        # Currently translating
        translating_layout = QHBoxLayout()
        translating_layout.addWidget(QLabel("Translating:"))
        self.translating_label = QLabel("—")
        self.translating_label.setStyleSheet("font-weight: bold; color: #cccccc;")
        translating_layout.addWidget(self.translating_label)
        translating_layout.addStretch()
        progress_layout.addLayout(translating_layout)
        
        # Progress bar with label
        item_progress_layout = QHBoxLayout()
        item_progress_layout.addWidget(QLabel("Progress:"))
        self.item_progress_label = QLabel("0/0")
        self.item_progress_label.setStyleSheet("font-weight: bold; color: #cccccc;")
        item_progress_layout.addWidget(self.item_progress_label)
        item_progress_layout.addStretch()
        progress_layout.addLayout(item_progress_layout)
        
        self.item_progress_bar = QProgressBar()
        self.item_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 3px;
                text-align: center;
                background-color: #2b2b2b;
                color: white;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #007acc;
                border-radius: 2px;
            }
        """)
        progress_layout.addWidget(self.item_progress_bar)
        
        # NOTE: Do not add progress_layout to the UI. Kept in memory only.

        settings_host = QWidget()
        settings_host.setObjectName("translationSettingsBar")
        settings_host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        settings_host.setStyleSheet(
            "#translationSettingsBar { background-color: transparent; }"
        )
        settings_layout = QVBoxLayout(settings_host)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(Spacing.MD)

        choices_host = QWidget()
        choices_host.setObjectName("translationRunChoices")
        choices_host.setStyleSheet(
            "QWidget#translationRunChoices { background: transparent; border: none; }"
        )
        settings_grid = QGridLayout(choices_host)
        self.settings_grid = settings_grid
        settings_grid.setContentsMargins(0, 0, 0, 0)
        settings_grid.setHorizontalSpacing(Spacing.MD)
        settings_grid.setVerticalSpacing(Spacing.XS)

        engine_label = QLabel("Engine")
        self.engine_label = engine_label
        engine_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.module_combo = QComboBox()
        self.module_combo.currentTextChanged.connect(self._on_module_changed)
        self.module_combo.setMinimumWidth(180)
        self.module_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        settings_grid.addWidget(engine_label, 0, 0)
        settings_grid.addWidget(self.module_combo, 1, 0)

        mode_label = QLabel("Run mode")
        self.mode_label = mode_label
        mode_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Translate")
        self.mode_combo.addItem("Estimate")
        self.mode_combo.addItem(BATCH_MODE_LABEL)
        self.mode_combo.setMinimumWidth(180)
        self.mode_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        self.mode_combo.activated.connect(self._mark_mode_user_selected)
        settings_grid.addWidget(mode_label, 0, 1)
        settings_grid.addWidget(self.mode_combo, 1, 1)
        settings_grid.setColumnStretch(0, 1)
        settings_grid.setColumnStretch(1, 1)
        settings_layout.addWidget(choices_host)

        manual_context_host = QFrame()
        manual_context_host.setObjectName("translationContextPanel")
        manual_context_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        manual_context_host.setStyleSheet(
            f"QFrame#translationContextPanel {{ background-color:{COLORS.surface_2};"
            f"border:1px solid {COLORS.border};border-radius:{Geometry.RADIUS_CONTROL}px; }}"
            "QFrame#translationContextPanel QLabel { border:none; background:transparent; }"
            f"QLabel[contextAsset=\"true\"] {{ color:{COLORS.text_muted};"
            f"background-color:{COLORS.surface_1};border:1px solid {COLORS.border};"
            f"border-radius:{Geometry.RADIUS_CONTROL}px;padding:4px 8px; }}"
            f"QLabel[contextAsset=\"true\"][available=\"true\"] {{ color:{COLORS.success};"
            f"border-color:{COLORS.border_strong}; }}"
        )
        manual_context_layout = QVBoxLayout(manual_context_host)
        manual_context_layout.setContentsMargins(
            Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD
        )
        manual_context_layout.setSpacing(Spacing.SM)

        context_heading_row = QHBoxLayout()
        context_heading_row.setContentsMargins(0, 0, 0, 0)
        context_heading_row.setSpacing(Spacing.SM)
        context_title = QLabel("Translation context")
        context_title.setStyleSheet(
            f"font-weight:600;color:{COLORS.text_primary};font-size:12px;"
        )
        context_heading_row.addWidget(context_title)
        context_description = QLabel(
            "Keep terminology, voice, and the game's translation frame together."
        )
        self.context_description = context_description
        context_description.setObjectName("appStatusText")
        context_description.setWordWrap(True)
        context_heading_row.addWidget(context_description, 1)
        manual_context_layout.addLayout(context_heading_row)

        self.manual_context_root_edit = QLineEdit()
        self.manual_context_root_edit.setReadOnly(True)
        self.manual_context_root_edit.setPlaceholderText(
            "No project selected — use the configured project when available"
        )
        self.manual_context_root_edit.setToolTip(
            "A project folder loads its glossary, game.md, quirks.md, and custom Markdown skills"
        )
        self.manual_context_browse_button = QPushButton("Choose…")
        configure_action_button(
            self.manual_context_browse_button,
            variant="secondary",
            tooltip="Choose a game/project folder; portable guidance is kept under .dazedtl",
        )
        self.manual_context_browse_button.clicked.connect(
            self._choose_manual_context_root
        )
        self.manual_context_clear_button = QPushButton("Reset")
        configure_action_button(
            self.manual_context_clear_button,
            variant="quiet",
            tooltip="Stop overriding the project configured by the selected engine workflow",
        )
        self.manual_context_clear_button.clicked.connect(
            self._clear_manual_context_root
        )
        manual_context_picker_row = QHBoxLayout()
        manual_context_picker_row.setContentsMargins(0, 0, 0, 0)
        manual_context_picker_row.setSpacing(Spacing.SM)
        manual_context_picker_row.addWidget(self.manual_context_root_edit, 1)
        manual_context_picker_row.addWidget(self.manual_context_browse_button)
        manual_context_picker_row.addWidget(self.manual_context_clear_button)
        manual_context_layout.addLayout(manual_context_picker_row)

        context_assets_row = QHBoxLayout()
        context_assets_row.setContentsMargins(0, 0, 0, 0)
        context_assets_row.setSpacing(Spacing.SM)
        self.context_asset_labels = {}
        for key, text in (
            ("glossary", "Glossary"),
            ("game", "Game frame"),
            ("quirks", "Quirks"),
            ("custom", "Custom skills"),
        ):
            label = QLabel(text)
            label.setProperty("contextAsset", True)
            label.setProperty("available", False)
            context_assets_row.addWidget(label)
            self.context_asset_labels[key] = label
        context_assets_row.addStretch(1)
        manual_context_layout.addLayout(context_assets_row)

        self.context_status_label = QLabel()
        self.context_status_label.setObjectName("appStatusText")
        self.context_status_label.setWordWrap(True)
        manual_context_layout.addWidget(self.context_status_label)

        context_divider = QFrame()
        context_divider.setFrameShape(QFrame.HLine)
        context_divider.setStyleSheet(f"color:{COLORS.border};")
        manual_context_layout.addWidget(context_divider)

        context_actions = QHBoxLayout()
        context_actions.setContentsMargins(0, 0, 0, 0)
        context_actions.setSpacing(Spacing.SM)
        self.copy_generic_setup_button = QPushButton("Copy setup skill")
        configure_action_button(
            self.copy_generic_setup_button,
            variant="secondary",
            tooltip="Copy a generic project-analysis skill that writes Glossary, Game frame, and Quirks",
        )
        self.copy_generic_setup_button.clicked.connect(
            self._copy_generic_project_setup
        )
        context_actions.addWidget(self.copy_generic_setup_button)

        self.review_context_button = QPushButton("Review files…")
        configure_action_button(
            self.review_context_button,
            variant="quiet",
            tooltip="Open tabbed editors for this project's Glossary, Game frame, Quirks, and custom skills",
        )
        self.review_context_button.clicked.connect(self._open_context_editor)
        context_actions.addWidget(self.review_context_button)
        context_actions.addStretch(1)
        manual_context_layout.addLayout(context_actions)
        self.manual_context_host = manual_context_host
        settings_layout.addWidget(manual_context_host)

        self.batch_mode_note = QLabel(
            "<b>Batch API</b> · typically 50% lower provider cost.<br>"
            "Fresh RPG Maker and WolfDawn batches resolve untranslated speaker names "
            "before submission; approving those names may use live API calls."
        )
        self.batch_mode_note.setTextFormat(Qt.RichText)
        self.batch_mode_note.setWordWrap(True)
        self.batch_mode_note.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.batch_mode_note.setStyleSheet(
            f"color:{COLORS.text_secondary};background-color:{COLORS.surface_2};"
            f"border:1px solid {COLORS.border};border-radius:{Geometry.RADIUS_CONTROL}px;"
            f"padding:{Spacing.SM}px {Spacing.MD}px;font-size:12px;"
        )
        self.batch_mode_note.setVisible(False)
        settings_layout.addWidget(self.batch_mode_note)

        action_host = QWidget()
        action_host.setObjectName("translationSettingsActions")
        action_host.setAttribute(Qt.WA_TranslucentBackground, True)
        action_host.setStyleSheet(
            "QWidget#translationSettingsActions { background: transparent; border: none; }"
        )
        action_row = QHBoxLayout(action_host)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(Spacing.SM)
        action_row.addStretch()

        self.translate_button = QPushButton("Translate selected files")
        self.translate_button.clicked.connect(self.start_translation)
        configure_action_button(self.translate_button, variant="primary")
        self.translate_button.setEnabled(False)
        action_row.addWidget(self.translate_button)
        self.settings_action_host = action_host
        settings_layout.addWidget(action_host)
        setup_card.add_widget(settings_host)
        self._manual_context_root = ""
        self._context_dialog = None
        self._refresh_manual_context_display()

        self.refresh_default_translation_mode(force=True)
        
        # Right side - translation history log viewer
        self.translation_log_viewer = LogViewer(show_header=False)
        # Mismatch counting is driven by MISMATCH_EVENT stdout markers
        # detected in append_log. The log_viewer signal is kept as a
        # fallback for in-process mode (e.g. speaker-parse).
        self.translation_log_viewer.mismatch_detected.connect(self.on_mismatch_detected)

        # The log is a primary feedback surface for Translation, so it remains
        # visible beside the setup/files/progress workspace in every state.
        left_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.translation_log_viewer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_card = SectionCard("Translation log", compact=True)
        self.log_card = log_card
        log_card.setMinimumWidth(360)
        log_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        log_card.add_widget(self.translation_log_viewer, 1)

        left_widget.setMinimumWidth(520)
        workspace_splitter = QSplitter(Qt.Horizontal)
        workspace_splitter.setObjectName("translationWorkspaceSplitter")
        workspace_splitter.setChildrenCollapsible(False)
        workspace_splitter.setHandleWidth(Spacing.MD)
        workspace_splitter.setStyleSheet(
            "QSplitter#translationWorkspaceSplitter::handle {"
            "background: transparent; border: none; }"
            f"QSplitter#translationWorkspaceSplitter::handle:hover {{"
            f"background: {COLORS.surface_hover}; }}"
        )
        workspace_splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        workspace_splitter.addWidget(left_widget)
        workspace_splitter.addWidget(log_card)
        workspace_splitter.setSizes([640, 640])
        workspace_splitter.setStretchFactor(0, 1)
        workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter = workspace_splitter
        workspace_splitter.splitterMoved.connect(
            lambda *_args: self._arrange_translation_workspace()
        )
        main_hbox.addWidget(workspace_splitter, 1)

        main_container.setLayout(main_hbox)

        # Ensure main container will expand to fill the tab vertically
        main_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Set main layout for this tab
        page_content = QWidget()
        page_content.setObjectName("appPage")
        page_content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        tab_layout = QVBoxLayout(page_content)
        tab_layout.setContentsMargins(
            Spacing.XL, Spacing.LG, Spacing.XL, Spacing.LG
        )
        tab_layout.setSpacing(Spacing.LG)
        tab_layout.addWidget(PageHeader(
            "Translation",
            "Configure the run, choose its files, and follow live translation output."
        ))
        # Add with stretch so the container expands to fill available space
        tab_layout.addWidget(main_container, 1)

        page_scroll = QScrollArea()
        page_scroll.setObjectName("translationPageScroll")
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page_scroll.setWidget(page_content)
        self.page_scroll = page_scroll

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        outer_layout.addWidget(page_scroll)
        QTimer.singleShot(0, self._arrange_translation_workspace)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._arrange_translation_workspace)

    def _arrange_translation_workspace(self) -> None:
        self._arrange_translation_settings()
        self._arrange_translation_file_controls()

    def _arrange_translation_file_controls(self) -> None:
        """Use one toolbar row whenever the file card has enough room."""
        if not all(
            hasattr(self, name)
            for name in (
                "file_card",
                "file_controls_layout",
                "selection_summary_label",
                "add_files_button",
                "remove_files_button",
                "more_file_actions_button",
                "select_all_button",
                "clear_selection_button",
            )
        ):
            return

        buttons = (
            self.add_files_button,
            self.remove_files_button,
            self.more_file_actions_button,
            self.select_all_button,
            self.clear_selection_button,
        )
        for button in buttons:
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)
        self.add_files_button.setText("Add files…")
        self.remove_files_button.setText("Remove selected")
        self.more_file_actions_button.setText("More…")
        self.select_all_button.setText("Select all")
        self.clear_selection_button.setText("Clear")
        summary_width = max(
            self.selection_summary_label.sizeHint().width(),
            self.fontMetrics().horizontalAdvance("000 of 000 selected"),
        )
        button_width = max(action_button_width_hint(button) for button in buttons)
        buttons_width = button_width * len(buttons) + Spacing.SM * (len(buttons) - 1)
        integrated_width = buttons_width + summary_width + Spacing.SM
        card_margins = self.file_card.content_layout.contentsMargins()
        available_width = max(
            0,
            self.file_card.width() - card_margins.left() - card_margins.right(),
        )
        if available_width >= integrated_width:
            mode = "integrated"
        elif available_width >= buttons_width:
            mode = "buttons"
        else:
            self.add_files_button.setText("Add")
            self.remove_files_button.setText("Remove")
            self.more_file_actions_button.setText("More")
            self.select_all_button.setText("All")
            self.clear_selection_button.setText("Clear")
            compact_button_width = max(
                action_button_width_hint(button) for button in buttons
            )
            compact_buttons_width = (
                compact_button_width * len(buttons)
                + Spacing.SM * (len(buttons) - 1)
            )
            if available_width >= compact_buttons_width + summary_width + Spacing.SM:
                mode = "compact-integrated"
            elif available_width >= compact_buttons_width:
                mode = "compact-row"
            else:
                mode = "compact-wrap"
        self._file_controls_layout_mode = mode

        # These controls form one toolbar. Keeping a single peer width avoids
        # the ragged two-group appearance when the toolbar wraps.
        equalize_button_widths(buttons, minimum=0)

        top = self.file_controls_top_layout
        bottom = self.file_controls_bottom_layout
        for row in (top, bottom):
            while row.count():
                row.takeAt(0)

        if mode in {"integrated", "compact-integrated"}:
            top.addWidget(self.add_files_button)
            top.addWidget(self.remove_files_button)
            top.addWidget(self.more_file_actions_button)
            top.addStretch(1)
            top.addWidget(self.selection_summary_label)
            top.addWidget(self.select_all_button)
            top.addWidget(self.clear_selection_button)
            self.file_controls_bottom_host.hide()
        elif mode in {"buttons", "compact-row"}:
            top.addWidget(self.selection_summary_label)
            top.addStretch(1)
            bottom.addWidget(self.add_files_button)
            bottom.addWidget(self.remove_files_button)
            bottom.addWidget(self.more_file_actions_button)
            bottom.addStretch(1)
            bottom.addWidget(self.select_all_button)
            bottom.addWidget(self.clear_selection_button)
            self.file_controls_bottom_host.show()
        else:
            # Keep the selection summary and its scope controls together, then
            # place the three file actions on one aligned row beneath them.
            top.addWidget(self.selection_summary_label)
            top.addStretch(1)
            top.addWidget(self.select_all_button)
            top.addWidget(self.clear_selection_button)
            bottom.addWidget(self.add_files_button)
            bottom.addWidget(self.remove_files_button)
            bottom.addWidget(self.more_file_actions_button)
            bottom.addStretch(1)
            self.file_controls_bottom_host.show()
        self.file_controls_top_host.show()
        self.file_toolbar.updateGeometry()

    def _arrange_translation_settings(self) -> None:
        """Keep supporting copy out of the way in the narrow split view."""
        if not hasattr(self, "context_description"):
            return
        self.context_description.setVisible(self.setup_card.width() >= 620)

    def setup_module_list(self):
        """Set up the module selection list."""
        # Engine modules read translation settings during import. A downloaded
        # source archive intentionally has no .env yet, so importing every
        # engine here used to abort discovery and leave only the fallback item.
        # Keep the UI registry independent and defer imports until a handler is
        # actually used.
        self.modules = [
            [
                display_name,
                list(extensions),
                _lazy_module_handler(module_name, handler_name),
            ]
            for display_name, extensions, module_name, handler_name
            in TRANSLATION_MODULE_SPECS
        ]

        for module in self.modules:
            extensions = ", ".join(module[1])
            self.module_combo.addItem(f"{module[0]} ({extensions})")
        if self.module_combo.count():
            self._on_module_changed(self.module_combo.currentText())

    def _on_module_changed(self, text: str):
        lowered = text.lower()
        if "wolf" in lowered and "wolf rpg 2" not in lowered:
            self.engine_changed.emit("wolf")
        elif "mv/mz" in lowered:
            self.engine_changed.emit("mvmz")
        elif "srpg" in lowered:
            self.engine_changed.emit("srpg")
        
        # Update mode dropdown based on engine
        current_mode = self.mode_combo.currentText()
        self.mode_combo.clear()
        self.mode_combo.addItem("Translate")
        self.mode_combo.addItem("Estimate")
        self.mode_combo.addItem(BATCH_MODE_LABEL)

        # Add Parse Speakers for RPG Maker MV/MZ
        if "mv/mz" in lowered:
            self.mode_combo.addItem("Parse Speakers")
        
        # Restore previous selection if it still exists
        index = self.mode_combo.findText(current_mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        else:
            default_idx = self.mode_combo.findText(default_translation_mode())
            self.mode_combo.setCurrentIndex(default_idx if default_idx >= 0 else 0)
        
        # Refresh file list to show only files matching the selected module's extensions
        self.refresh_file_lists()
        self._refresh_manual_context_display()
        self._reload_open_context_dialog()
    
    def _on_mode_changed(self, mode_text):
        """Update the translate button text based on selected mode."""
        if hasattr(self, "batch_mode_note"):
            self.batch_mode_note.setVisible(mode_text == BATCH_MODE_LABEL)
        if not hasattr(self, "translate_button"):
            return
        if mode_text == "Translate":
            self.translate_button.setText("Start Translation")
        elif mode_text == "Estimate":
            self.translate_button.setText("Start Estimation")
        elif mode_text == BATCH_MODE_LABEL:
            self.translate_button.setText("Start Batch Translation")
        elif mode_text == "Parse Speakers":
            self.translate_button.setText("Parse Speakers")

    def _effective_manual_context_root(self) -> tuple[str, bool]:
        """Return the direct-run project context and whether it is overridden."""
        override = str(getattr(self, "_manual_context_root", "") or "").strip()
        if override:
            return override, True
        module_name = self.module_combo.currentText().split(" (", 1)[0]
        return _configured_game_root(self.settings, module_name), False

    def _refresh_manual_context_display(self) -> None:
        if not hasattr(self, "manual_context_root_edit"):
            return
        root, overridden = self._effective_manual_context_root()
        self.manual_context_root_edit.setText(root)
        self.manual_context_root_edit.setCursorPosition(0)
        self.manual_context_clear_button.setVisible(overridden)
        context_ready = bool(root and Path(root).is_dir())
        self.copy_generic_setup_button.setEnabled(context_ready)
        self.review_context_button.setEnabled(context_ready)

        inventory = _translation_context_inventory(root)
        for key, label in self.context_asset_labels.items():
            value = inventory[key]
            available = bool(value)
            label.setProperty("available", available)
            if key == "custom":
                count = len(value)
                label.setText(f"✓ Custom · {count}" if count else "— Custom")
                label.setToolTip(
                    "\n".join(str(path) for path in value)
                    if count
                    else "No custom Markdown skill overlays found"
                )
            else:
                names = {
                    "glossary": "Glossary",
                    "game": "Game frame",
                    "quirks": "Quirks",
                }
                label.setText(
                    f"✓ {names[key]}" if available else f"— {names[key]}"
                )
                label.setToolTip(
                    str(value)
                    if available
                    else f"No {names[key].lower()} file found in this project"
                )
            refresh_style(label)

        if not root:
            self.context_status_label.setText(
                "No project context is configured. The base translation skill still applies."
            )
            self.context_status_label.setProperty("state", "neutral")
        elif not Path(root).is_dir():
            self.context_status_label.setText(
                "The selected project folder is missing. Choose another project before running."
            )
            self.context_status_label.setProperty("state", "error")
        else:
            source = "Selected project" if overridden else "Configured project"
            custom_count = len(inventory["custom"])
            available_count = sum(
                bool(inventory[key]) for key in ("glossary", "game", "quirks")
            ) + custom_count
            if available_count:
                self.context_status_label.setText(
                    f"{source} · {Path(root).name} · {available_count} context "
                    f"{'file' if available_count == 1 else 'files'} will be merged."
                )
                self.context_status_label.setProperty("state", "success")
            else:
                self.context_status_label.setText(
                    f"{source} · {Path(root).name} · no project guidance files found yet."
                )
                self.context_status_label.setProperty("state", "warning")
        refresh_style(self.context_status_label)

    def _choose_manual_context_root(self) -> None:
        """Choose a complete project context for direct Translation-page runs."""
        current, _overridden = self._effective_manual_context_root()
        start = current
        if not start:
            try:
                start = str(self.settings.value("last_open_dir", "") or "")
            except Exception:
                start = ""
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select project context folder",
            start,
        )
        if not selected:
            return
        self._manual_context_root = str(Path(selected).expanduser().resolve())
        self._refresh_manual_context_display()
        self._reload_open_context_dialog()
        try:
            if self.settings:
                self.settings.setValue("last_open_dir", self._manual_context_root)
        except Exception:
            pass

    def _clear_manual_context_root(self) -> None:
        self._manual_context_root = ""
        self._refresh_manual_context_display()
        self._reload_open_context_dialog()

    def _copy_generic_project_setup(self) -> bool:
        """Copy the generic context skill for the selected project folder."""
        root, _overridden = self._effective_manual_context_root()
        if not root or not Path(root).is_dir():
            QMessageBox.warning(
                self,
                "Project context",
                "Choose an existing project folder before copying the setup skill.",
            )
            return False
        try:
            prepare_game_translation_context(root)
            QApplication.clipboard().setText(load_generic_project_setup(root))
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Project context",
                f"Could not prepare the generic setup skill:\n\n{exc}",
            )
            return False

        self._refresh_manual_context_display()
        self.context_status_label.setText(
            f"Setup skill copied for {Path(root).name}. Run it in your AI helper, "
            "then review the generated files."
        )
        self.context_status_label.setProperty("state", "success")
        refresh_style(self.context_status_label)
        return True

    def _open_context_editor(self) -> None:
        root, _overridden = self._effective_manual_context_root()
        if not root or not Path(root).is_dir():
            QMessageBox.warning(
                self,
                "Project context",
                "Choose an existing project folder before reviewing its guidance files.",
            )
            return
        if self._context_dialog is None:
            self._context_dialog = TranslationContextDialog(
                self,
                game_root_fn=lambda: self._effective_manual_context_root()[0],
                copy_setup_fn=self._copy_generic_project_setup,
            )
            self._context_dialog.context_changed.connect(
                self._refresh_manual_context_display
            )
        self._context_dialog.reload_context()
        self._context_dialog.show()
        self._context_dialog.raise_()
        self._context_dialog.activateWindow()

    def _reload_open_context_dialog(self) -> None:
        dialog = getattr(self, "_context_dialog", None)
        if dialog is not None and dialog.isVisible():
            dialog.reload_context()

    def _set_manual_context_controls_visible(self, visible: bool) -> None:
        self.manual_context_host.setVisible(visible)

    def prepare_manual_translation(self) -> None:
        """Expose standalone controls when the sidebar opens Translation directly."""
        if self.file_stack.currentIndex() != 0 or self._active_workflow_return:
            return
        self._pending_workflow_return = None
        self._refresh_manual_context_display()
        self._set_manual_context_controls_visible(True)

    def _set_activity_visible(self, visible: bool) -> None:
        """Keep the Translation Log visible; it is core run feedback."""
        if not hasattr(self, "translation_log_viewer"):
            return
        self.translation_log_viewer.show()

    def _set_run_controls_enabled(self, enabled: bool) -> None:
        """Lock run-defining choices while a worker or completed result is active."""
        for widget in (
            getattr(self, "module_combo", None),
            getattr(self, "mode_combo", None),
            getattr(self, "manual_context_host", None),
        ):
            if widget is not None:
                widget.setEnabled(enabled)
        if hasattr(self, "translate_button"):
            self.translate_button.setEnabled(enabled and bool(self.get_selected_files()))

    def _mark_mode_user_selected(self, _index: int):
        self._mode_user_selected = True

    def refresh_default_translation_mode(self, force=False):
        """Refresh the provider-aware default without overriding an active choice."""
        default_mode = default_translation_mode()
        if not force and default_mode == self._last_default_translation_mode:
            return
        self._last_default_translation_mode = default_mode
        if default_mode == "Translate" or force or not self._mode_user_selected:
            index = self.mode_combo.findText(default_mode)
            if index >= 0:
                self.mode_combo.setCurrentIndex(index)

    def _switch_progress_tab(self, index):
        """Switch Batch/Files views; index 0 = batch overview, 1 = per-file list."""
        self._batch_tab_index = index if self.progress_tab_row.isVisible() else -1
        self.progress_content_stack.setCurrentIndex(index)
        self.batch_tab_btn.setChecked(index == 0)
        self.files_tab_btn.setChecked(index == 1)

    def _set_progress_view_mode(self, batch_mode, file_count=0):
        """Batch runs use a Batch tab for the pipeline; Files tab holds the per-file list."""
        if batch_mode:
            self.progress_tab_row.setVisible(True)
            self.batch_pipeline_widget.setVisible(True)
            self.files_tab_btn.setText(f"Files ({file_count})" if file_count else "Files")
            self._switch_progress_tab(0)
        else:
            self.progress_tab_row.setVisible(False)
            self.batch_pipeline_widget.setVisible(False)
            self.files_tab_btn.setText("Files")
            self._batch_tab_index = -1
            self.progress_content_stack.setCurrentIndex(1)
        # Per-file Time is useful for live translate; for batch, the provider owns
        # the wait and local write time is negligible.
        table = getattr(self, "progress_table", None)
        if table is not None and table.columnCount() > 5:
            table.setColumnHidden(5, bool(batch_mode))
        try:
            if hasattr(self, "totals_time_label"):
                self.totals_time_label.setVisible(not batch_mode)
        except Exception:
            pass

    def _on_batch_submit_yes(self):
        if hasattr(self, "translation_worker") and self.translation_worker:
            self.batch_submit_yes_btn.setEnabled(False)
            self.batch_submit_no_btn.setEnabled(False)
            self.translation_worker.set_batch_submit_response(True)

    def _on_batch_submit_no(self):
        if hasattr(self, "translation_worker") and self.translation_worker:
            self.batch_submit_yes_btn.setEnabled(False)
            self.batch_submit_no_btn.setEnabled(False)
            self.translation_worker.set_batch_submit_response(False)

    def _on_speaker_confirmation(self, payload):
        """Approve one grouped speaker-translation phase after a no-API scan."""
        worker = getattr(self, "translation_worker", None)
        if worker is None:
            return
        estimate = payload if isinstance(payload, dict) else {}
        raw_names = estimate.get("speakers", []) if estimate else (payload or [])
        names = [str(name).strip() for name in raw_names if str(name).strip()]
        preview_limit = 12
        preview = "\n".join(f"  • {name}" for name in names[:preview_limit])
        if len(names) > preview_limit:
            preview += f"\n  • …and {len(names) - preview_limit} more"
        estimate_text = ""
        if estimate:
            cache_note = " (conservative cold-cache estimate)" if estimate.get("cold_cache") else ""
            estimate_text = (
                "Estimated speaker translation:\n"
                f"  Model: {estimate.get('model', 'Unknown')}\n"
                f"  Grouped requests: {int(estimate.get('request_count', 0)):,}\n"
                f"  Tokens: {int(estimate.get('input_tokens', 0)):,} input / "
                f"{int(estimate.get('output_tokens', 0)):,} output\n"
                f"  Cost: approximately ${float(estimate.get('estimated_cost', 0.0)):.6f}"
                f"{cache_note}\n\n"
            )
        reply = QMessageBox.question(
            self,
            "Translate collected speakers?",
            f"DazedTL found {len(names)} unresolved unique speaker(s). No speaker "
            "translation requests have been sent yet.\n\n"
            f"{estimate_text}"
            f"{preview}\n\n"
            "Translate these names together in grouped list batches, save them to "
            "this game's glossary, and then continue the translation run?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        worker.set_speaker_translation_response(reply == QMessageBox.Yes)

    def _update_batch_stop_button(self):
        """Show stop only while batch is collecting; hide after that."""
        if not getattr(self, "_batch_active", False):
            return
        try:
            self.stop_button.setVisible(self._batch_ui_phase == "collect")
        except Exception:
            pass

    def _batch_step_style(self, state: str) -> str:
        """CSS for a pipeline step chip: idle | active | done."""
        if state == "active":
            return (
                "color:#ffffff;background:#007acc;border:1px solid #007acc;"
                "border-radius:4px;padding:4px 6px;font-size:11px;font-weight:bold;"
            )
        if state == "done":
            return (
                "color:#4ec9b0;background:#1e1e1e;border:1px solid #4ec9b0;"
                "border-radius:4px;padding:4px 6px;font-size:11px;"
            )
        return (
            "color:#888888;background:#1e1e1e;border:1px solid #3e3e42;"
            "border-radius:4px;padding:4px 6px;font-size:11px;"
        )

    def _set_batch_steps(self, active_index: int):
        """Highlight pipeline steps. active_index 0..3, or 4 when fully done."""
        labels = getattr(self, "_batch_step_labels", None) or []
        for i, lab in enumerate(labels):
            if i < active_index:
                lab.setStyleSheet(self._batch_step_style("done"))
            elif i == active_index and active_index < 4:
                lab.setStyleSheet(self._batch_step_style("active"))
            elif active_index >= 4:
                lab.setStyleSheet(self._batch_step_style("done"))
            else:
                lab.setStyleSheet(self._batch_step_style("idle"))

    def _update_batch_poll_dashboard(self, statuses):
        """Render structured provider batch statuses into the poll panel."""
        if not isinstance(statuses, list) or not statuses:
            return
        totals = {"processing": 0, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0}
        ids = []
        api_states = []
        expected = 0
        for st in statuses:
            ids.append(st.get("id") or "")
            api_states.append(st.get("api_status") or "")
            expected += int(st.get("request_count") or 0)
            for k, v in (st.get("counts") or {}).items():
                if k in totals:
                    totals[k] += int(v or 0)
        done = totals["succeeded"] + totals["errored"] + totals["canceled"] + totals["expired"]
        total = max(expected, done + totals["processing"], 1)
        if hasattr(self, "batch_poll_id"):
            self.batch_poll_id.setText("Batch: " + (", ".join(i for i in ids if i) or "—"))
        for key, lab in (getattr(self, "_batch_count_labels", {}) or {}).items():
            lab.setText(f"{key}: {totals.get(key, 0)}")
        if hasattr(self, "batch_poll_bar"):
            self.batch_poll_bar.setRange(0, total)
            self.batch_poll_bar.setValue(min(done, total))
            self.batch_poll_bar.setFormat(f"Requests finished: {done} / {total}")
        # Overall bar: process phase spans ~55-80%
        frac = done / total if total else 0
        self.batch_overall_bar.setValue(55 + int(20 * frac))
        state_txt = ", ".join(sorted(set(api_states))) or "unknown"
        self.batch_poll_status.setText(
            f"Provider status: {state_txt}\n"
            f"{totals['succeeded']} succeeded, {totals['processing']} still processing"
            + (f", {totals['errored']} errored" if totals["errored"] else "")
            + (f", {totals['canceled']} canceled" if totals["canceled"] else "")
            + (f", {totals['expired']} expired" if totals["expired"] else "")
            + "."
        )
        self.batch_live_status.setText(
            f"Polling… {done}/{total} requests finished. Details stay in the Translation Log."
        )

    def _on_batch_phase(self, phase, payload):
        """Update the inline batch pipeline panel for the current phase."""
        self._batch_ui_phase = phase
        self.batch_pipeline_widget.setVisible(True)

        if phase == "collect":
            self.batch_overall_bar.setFormat("%p%")
            self._set_batch_steps(0)
            self.batch_phase_title.setText("Batch Translate - Pass 1/2: Collect")
            self.batch_overall_bar.setRange(0, 100)
            self.batch_overall_bar.setValue(15)
            self.batch_pipeline_stack.setCurrentIndex(0)
            self.batch_submit_yes_btn.setText("Submit Batch")
            self.batch_collect_status.setText(
                "Scanning files and queueing dialogue for the batch…"
            )
        elif phase == "collect_done":
            info = payload or {}
            n_files = info.get("files", "?")
            n_req = info.get("requests", "?")
            self._set_batch_steps(1)
            self.batch_phase_title.setText("Batch Translate - Collect complete")
            self.batch_overall_bar.setValue(30)
            self.batch_pipeline_stack.setCurrentIndex(0)
            self.batch_collect_status.setText(
                f"Finished scanning {n_files} file(s) - {n_req} API request(s) queued.\n"
                "Review the cost estimate, then submit once for the whole batch."
            )
            self.batch_live_status.setText(
                f"All {n_files} files collected. Open the Files tab to inspect per-file rows."
            )
        elif phase == "submit":
            est = payload or {}
            n_files = est.get("files", "?")
            n_req = est.get("requests", "?")
            model_name = str(est.get("model") or os.getenv("model", "") or "—")
            display_model = model_name.removeprefix("models/")
            input_tokens = int(est.get("input_tokens") or est.get("dynamic_tokens") or 0)
            output_tokens = int(est.get("output_tokens") or 0)
            estimate_lines = [
                f"{n_files} file(s) scanned - {n_req} request(s) queued.",
                f"Model: {display_model}",
                f"Approximate tokens: {input_tokens:,} input / ~{output_tokens:,} visible output.",
            ]
            if est.get("unestimated_thinking_tokens"):
                estimate_lines.append(
                    "Gemini thinking tokens are billed as output and are not predictable "
                    "before the run, so the totals below exclude them."
                )
            estimate_lines.extend((
                "",
                "One provider submission covers every queued request (typically 50% batch discount). "
                "You can stop safely after submit and resume later.",
            ))
            self._set_batch_steps(1)
            self.batch_phase_title.setText("Batch Translate - Review & Submit")
            self.batch_overall_bar.setValue(35)
            self.batch_pipeline_stack.setCurrentIndex(1)
            self.batch_submit_yes_btn.setEnabled(True)
            self.batch_submit_no_btn.setEnabled(True)
            self.batch_submit_summary.setText("\n".join(estimate_lines))
            if hasattr(self, "batch_cost_cached"):
                uses_prompt_cache = bool(est.get("uses_prompt_cache"))
                self.batch_cost_cached.setVisible(uses_prompt_cache)
                if uses_prompt_cache:
                    cached_label = (
                        "Batch + auto cache"
                        if est.get("cache_kind") == "automatic"
                        else "Batch + cache"
                    )
                    self.batch_cost_cached.setText(
                        f"{cached_label}\n"
                        f"{_format_estimated_cost(est.get('batch_cached_cost'))}"
                    )
                    batch_label = "Batch worst-case"
                else:
                    batch_label = "Batch estimate"
                thinking_suffix = " + thinking" if est.get("unestimated_thinking_tokens") else ""
                self.batch_cost_nocache.setText(
                    f"{batch_label}\n"
                    f"{_format_estimated_cost(est.get('batch_nocache_cost'))}{thinking_suffix}"
                )
                self.batch_cost_live.setText(
                    "Live API\n"
                    f"{_format_estimated_cost(est.get('live_cost'))}{thinking_suffix}"
                )
            self.batch_submit_yes_btn.setText(f"Submit All ({n_req} requests)")
        elif phase == "canceled":
            info = payload or {}
            n_req = info.get("requests", "?")
            self._set_batch_steps(1)
            self.batch_phase_title.setText("Batch Translate - Canceled")
            self.batch_overall_bar.setRange(0, 100)
            self.batch_overall_bar.setValue(35)
            self.batch_overall_bar.setFormat("Canceled")
            self.batch_pipeline_stack.setCurrentIndex(1)
            self.batch_submit_summary.setText(
                f"Canceled {n_req} queued request(s). Nothing was sent to the provider, "
                "and the local queue was discarded."
            )
            self.batch_live_status.setText("Batch canceled - no provider job was created.")
        elif phase == "no_work":
            info = payload or {}
            n_files = info.get("files", "?")
            self._set_batch_steps(1)
            self.batch_phase_title.setText("Batch Translate - No work found")
            self.batch_overall_bar.setRange(0, 100)
            self.batch_overall_bar.setValue(25)
            self.batch_overall_bar.setFormat("No batch submitted")
            self.batch_pipeline_stack.setCurrentIndex(0)
            self.batch_collect_status.setText(
                f"Scanned {n_files} file(s), but found no eligible untranslated text.\n"
                "No request was queued or sent to the provider."
            )
            self.batch_live_status.setText("Scan complete - nothing to submit.")
            self._mark_batch_files_no_work()
        elif phase == "polling":
            self._set_batch_steps(2)
            self.batch_phase_title.setText("Batch Translate - Processing")
            self.batch_overall_bar.setRange(0, 100)
            self.batch_overall_bar.setFormat("%p%")
            self.batch_overall_bar.setValue(55)
            self.batch_pipeline_stack.setCurrentIndex(2)
            self.batch_poll_status.setText("Submitted - waiting for the provider to process the batch…")
            if hasattr(self, "batch_poll_bar"):
                self.batch_poll_bar.setRange(0, 100)
                self.batch_poll_bar.setValue(0)
                self.batch_poll_bar.setFormat("Waiting for first status…")
        elif phase == "poll_status":
            self._set_batch_steps(2)
            self.batch_phase_title.setText("Batch Translate - Processing")
            self.batch_overall_bar.setFormat("%p%")
            self.batch_pipeline_stack.setCurrentIndex(2)
            self._update_batch_poll_dashboard(payload)
        elif phase == "consume":
            self._batch_consume_started = True
            self._set_batch_steps(3)
            self.batch_phase_title.setText("Batch Translate - Pass 2/2: Write")
            self.batch_overall_bar.setFormat("%p%")
            self.batch_overall_bar.setValue(80)
            self.batch_pipeline_stack.setCurrentIndex(3)
            self.batch_consume_status.setText("Pass 2/2: writing translated files from batch results…")
            self._reset_files_for_consume()
            if self.progress_tab_row.isVisible():
                self._switch_progress_tab(0)
        elif phase == "done":
            info = payload or {}
            mismatch_count = max(0, int(info.get("mismatches") or 0))
            self._batch_mismatch_count = mismatch_count
            self._set_batch_steps(4)
            self.batch_overall_bar.setValue(100)
            self.batch_pipeline_stack.setCurrentIndex(3)
            if mismatch_count:
                summary = _mismatch_summary(mismatch_count)
                self.batch_overall_bar.setFormat("Completed with warnings")
                self.batch_phase_title.setText(
                    "Batch Translate - Complete with warnings"
                )
                self.batch_consume_status.setText(
                    f"Pass 2/2 finished with {summary}. Translations were written; "
                    "original text was kept for those chunks. Review Issues in the "
                    "translation log."
                )
                self.batch_live_status.setText(
                    f"Batch complete - {summary} to review"
                )
            else:
                self.batch_overall_bar.setFormat("%p%")
                self.batch_phase_title.setText("Batch Translate - Complete")
                self.batch_consume_status.setText(
                    "Pass 2/2 finished. Translations written - use the back arrow "
                    "to return to the file list."
                )
                self.batch_live_status.setText("Batch complete")
        elif phase == "failed":
            info = payload or {}
            message = str(info.get("message") or "Batch run failed")
            self.batch_phase_title.setText("Batch Translate - Failed")
            self.batch_overall_bar.setRange(0, 100)
            self.batch_overall_bar.setFormat("Failed")
            self.batch_live_status.setText(message)

        self._update_batch_stop_button()

    def _reset_batch_pipeline_ui(self):
        self._batch_active = False
        self._batch_ui_phase = None
        self._batch_consume_started = False
        if hasattr(self, "batch_pipeline_widget"):
            self.batch_pipeline_widget.setVisible(False)
        if hasattr(self, "batch_live_status"):
            self.batch_live_status.setText("")
        if hasattr(self, "progress_content_stack"):
            self._set_progress_view_mode(False)
        elif hasattr(self, "batch_overall_bar"):
            self.batch_overall_bar.setRange(0, 100)
            self.batch_overall_bar.setValue(0)

    def _reset_files_for_consume(self):
        """Clear collect-pass row state before the consume pass writes translations."""
        self.files_completed = 0
        self.files_translated_label.setText(f"0/{self.files_total}")
        for filename, item in self.file_progress_items.items():
            try:
                item["checkbox"].setChecked(False)
                item["label"].setText("Waiting...")
                item["progress_bar"].setValue(0)
                item["progress_bar"].setMaximum(100)
                item["tokens_label"].setText("")
                item["cost_label"].setText("")
                item["time_label"].setText("")
                item["status_label"].setText("")
                item.pop("_skip_reason", None)
            except Exception:
                pass
            self._set_progress_row(
                filename,
                status="Waiting",
                status_color="#888888",
                progress="-",
                tokens="-",
                cost="-",
                time_s="-",
            )
        if hasattr(self, "_applied_file_totals"):
            self._applied_file_totals.clear()
        self.totals_input_tokens = 0
        self.totals_output_tokens = 0
        self.totals_cost = 0.0
        self.totals_time = 0.0
        try:
            if hasattr(self, "totals_tokens_label"):
                self.totals_tokens_label.setText("Tokens: 0 in / 0 out")
            if hasattr(self, "totals_cost_label"):
                self.totals_cost_label.setText("Cost: $0.0000")
            if hasattr(self, "totals_time_label"):
                self.totals_time_label.setText("Time: 0.0s")
        except Exception:
            pass

    def _mark_batch_files_no_work(self):
        """Replace collect-pass 'queued' rows when no API work was produced."""
        for filename, item in self.file_progress_items.items():
            try:
                item["checkbox"].setChecked(False)
                item["label"].setText("Skipped")
                item["progress_bar"].setMaximum(100)
                item["progress_bar"].setValue(0)
            except Exception:
                pass
            self._set_progress_row(
                filename,
                status="Skipped",
                status_color="#888888",
                progress="no eligible text",
                tokens="-",
                cost="-",
            )

    def mark_file_queued(self, filename):
        """Collect pass finished for a file - queued for batch, not translated yet."""
        if filename not in self.file_progress_items:
            return
        item = self.file_progress_items[filename]
        try:
            item["label"].setText("Collected")
            item["progress_bar"].setMaximum(100)
            item["progress_bar"].setValue(100)
            item["checkbox"].setChecked(False)
        except Exception:
            pass
        self._set_progress_row(
            filename,
            status="Collected",
            status_color="#d4a017",
            progress="queued",
        )

    def _check_model_pricing(self):
        """Fetch live pricing for the current model and print it to the log."""
        from dotenv import dotenv_values
        from pathlib import Path as _Path

        # Read model from .env file directly so we always get the saved value
        env = dotenv_values(_Path(".env")) if _Path(".env").exists() else {}
        model = env.get("model") or os.getenv("model", "").strip()

        log = self.translation_log_viewer

        if not model:
            log.append_log_message("💰 [PRICING] No model configured — set a model in Settings first.")
            return

        log.append_log_message(f"💰 [PRICING] Checking pricing for: {model}")

        try:
            from util.translation import _lookup_model_price, _load_litellm_pricing
        except Exception as e:
            log.append_log_message(f"💰 [PRICING] Could not import pricing module: {e}")
            return

        # Force a fresh fetch attempt (bypasses the in-memory TTL check by
        # temporarily clearing the in-memory cache timestamp)
        try:
            import util.translation as _tmod
            _tmod._pricing_db_fetched_at = 0.0
            _tmod._pricing_fetch_warned = False
        except Exception:
            pass

        db = _load_litellm_pricing()
        if db is None:
            log.append_log_message(
                "💰 [PRICING] Could not reach LiteLLM pricing DB — no internet or cache available. "
                "Falling back to built-in prices."
            )
        else:
            log.append_log_message(f"💰 [PRICING] LiteLLM DB loaded ({len(db):,} entries).")

        result = _lookup_model_price(model)
        if result:
            inp, out = result
            source = "LiteLLM" if db else "built-in fallback"
            log.append_log_message(
                f"💰 [PRICING] {model}  —  "
                f"Input: ${inp:.4f} / 1M tokens  |  "
                f"Output: ${out:.4f} / 1M tokens  "
                f"(source: {source})"
            )
        else:
            # Fall back to getPricingConfig for the hardcoded table result
            try:
                from util.translation import getPricingConfig
                cfg = getPricingConfig(model)
                log.append_log_message(
                    f"💰 [PRICING] {model} not found in LiteLLM DB — using built-in fallback:  "
                    f"Input: ${cfg['inputAPICost']:.4f} / 1M tokens  |  "
                    f"Output: ${cfg['outputAPICost']:.4f} / 1M tokens"
                )
            except Exception as e:
                log.append_log_message(f"💰 [PRICING] Could not determine pricing for '{model}': {e}")

    def refresh_file_lists(self):
        """Refresh the file list with checkboxes, preserving checked states."""
        # Save current check states from existing QListWidgetItems
        checked_files = set()
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            try:
                if item.checkState() == Qt.Checked:
                    checked_files.add(item.text())
            except Exception:
                pass

        # Get accepted extensions for the currently selected module
        accepted_extensions = []
        try:
            selected_index = self.module_combo.currentIndex()
            if 0 <= selected_index < len(self.modules):
                accepted_extensions = self.modules[selected_index][1]  # List of extensions like [".json"]
        except Exception:
            pass

        # Rebuild the list using simple QListWidgetItems with checkboxes
        self.file_list.clear()
        if self.files_dir.exists():
            for file_path in sorted(self.files_dir.iterdir()):
                if file_path.is_file() and file_path.name != '.gitkeep':
                    # Filter by accepted extensions if any are defined
                    if accepted_extensions:
                        file_ext = file_path.suffix.lower()
                        # Skip files that don't match any accepted extension
                        if not any(file_ext == ext.lower() for ext in accepted_extensions):
                            continue
                    
                    item = QListWidgetItem(file_path.name)
                    # Ensure the item is enabled, selectable, and user-checkable
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    # Restore checked state if it was previously checked
                    if file_path.name in checked_files:
                        item.setCheckState(Qt.Checked)
                    else:
                        item.setCheckState(Qt.Unchecked)
                    self.file_list.addItem(item)
        self._update_selection_summary()

    def _update_selection_summary(self, *_args) -> None:
        """Keep the run scope explicit and prevent empty starts."""
        if not hasattr(self, "file_list") or not hasattr(self, "selection_summary_label"):
            return
        total = self.file_list.count()
        selected = len(self.get_selected_files())
        if total == 0:
            text = "No matching files · add files or choose another engine"
        else:
            text = f"{selected} of {total} selected"
        self.selection_summary_label.setText(text)
        worker = getattr(self, "translation_worker", None)
        running = bool(worker and worker.isRunning())
        if hasattr(self, "translate_button") and self.file_stack.currentIndex() == 0:
            self.translate_button.setEnabled(selected > 0 and not running)
    
    def select_all_files(self):
        """Select all files in the list."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            try:
                item.setCheckState(Qt.Checked)
            except Exception:
                pass
        self._update_selection_summary()
    
    def deselect_all_files(self):
        """Deselect all files in the list."""
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            try:
                item.setCheckState(Qt.Unchecked)
            except Exception:
                pass
        self._update_selection_summary()
    
    def get_selected_files(self):
        """Get list of checked files."""
        selected = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            try:
                if item.checkState() == Qt.Checked:
                    selected.append(item.text())
            except Exception:
                pass
        return selected

    def select_files_by_name(self, file_names):
        """Check the given relative file names (and uncheck others)."""
        wanted = set(file_names or [])
        if not wanted:
            return
        self.refresh_file_lists()
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            try:
                item.setCheckState(Qt.Checked if item.text() in wanted else Qt.Unchecked)
            except Exception:
                pass
    
    def add_input_files(self):
        """Add files to the input directory, remembering last used directory."""
        # Restore last used directory from settings if available
        start_dir = ""
        try:
            if self.settings:
                start_dir = self.settings.value("last_open_dir", "") or ""
        except Exception:
            start_dir = ""

        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select files to add",
            start_dir,
            "All Files (*)"
        )
        
        if file_paths:
            # Save the directory used so next time we open the same place
            try:
                if self.settings and len(file_paths) > 0:
                    import os
                    dir_used = os.path.dirname(file_paths[0])
                    self.settings.setValue("last_open_dir", dir_used)
            except Exception:
                pass
            try:
                import shutil
                copied_count = 0
                for file_path in file_paths:
                    source = Path(file_path)
                    dest = self.files_dir / source.name
                    
                    if dest.exists():
                        reply = QMessageBox.question(
                            self,
                            "File Exists",
                            f"File '{source.name}' already exists. Overwrite?",
                            QMessageBox.Yes | QMessageBox.No
                        )
                        if reply == QMessageBox.No:
                            continue
                    
                    shutil.copy2(source, dest)
                    copied_count += 1
                
                self.refresh_file_lists()
                if copied_count > 0:
                    QMessageBox.information(self, "Files Added", f"Successfully added {copied_count} files.")
                    
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to add files:\n{str(e)}")
                
    def remove_selected_files(self):
        """Remove selected (checked) files from the input directory."""
        selected_files = self.get_selected_files()
        
        if not selected_files:
            QMessageBox.information(self, "No Selection", "Please check files to remove.")
            return
            
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete {len(selected_files)} file(s)?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                for filename in selected_files:
                    file_path = self.files_dir / filename
                    file_path.unlink()
                self.refresh_file_lists()
                QMessageBox.information(self, "Files Removed", f"Successfully removed {len(selected_files)} file(s).")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete files:\n{str(e)}")
    
    def open_input_folder(self):
        """Open the input directory."""
        self.open_folder(self.files_dir)
        
    def open_output_folder(self):
        """Open the output directory."""
        self.open_folder(self.translated_dir)

    def _sync_translated_to_files(self):
        """Copy translated/ files back into files/ (only matching names)."""
        import shutil
        files_dir = Path("files")
        transl_dir = Path("translated")

        if not transl_dir.exists():
            QMessageBox.warning(self, "Sync", "translated/ folder not found — nothing to sync.")
            return

        active = {fp.name for fp in files_dir.glob("*.json")} if files_dir.exists() else set()
        to_copy = [fp for fp in transl_dir.glob("*.json") if not active or fp.name in active]

        if not to_copy:
            QMessageBox.warning(self, "Sync", "No matching files found in translated/ to sync.")
            return

        files_dir.mkdir(exist_ok=True)
        copied = 0
        for src in to_copy:
            shutil.copy2(src, files_dir / src.name)
            copied += 1

        QMessageBox.information(self, "Sync Complete", f"Synced {copied} file(s) from translated/ → files/")
        self.refresh_file_lists()

    def _export_selected_files(self):
        """Export only the currently checked files in the file list."""
        selected = self.get_selected_files()
        if not selected:
            QMessageBox.warning(self, "Export", "No files are checked — select files to export first.")
            return
        self._export_active_files(filenames=selected)

    def _export_last_run_files(self):
        """Export only the files that were part of the most recent translation run."""
        if not self._last_run_files:
            QMessageBox.warning(self, "Export", "No translation run recorded — translate some files first.")
            return
        self._export_active_files(filenames=self._last_run_files)

    def _sync_and_export_last_run_files(self):
        """Sync the latest run to files/ and export it to the RPG Maker game."""
        if not self._last_run_files:
            QMessageBox.warning(
                self,
                "Sync & Export",
                "No translation run recorded — translate some files first.",
            )
            return

        translated_dir = self.translated_dir
        exportable = [
            name
            for name in self._last_run_files
            if name != ".gitkeep" and (translated_dir / name).is_file()
        ]
        if not exportable:
            QMessageBox.warning(
                self,
                "Sync & Export",
                "None of this run's translated files were found.",
            )
            return

        game_data = None
        try:
            workflow = getattr(self.window(), "workflow_tab", None)
            if workflow and getattr(workflow, "_data_path", None):
                game_data = workflow._data_path
        except Exception:
            pass
        if not game_data:
            game_data = QFileDialog.getExistingDirectory(
                self, "Select Game Data Folder to Export Into"
            )
            if not game_data:
                return

        reply = QMessageBox.question(
            self,
            "Sync & Export Translation Run",
            f"Copy {len(exportable)} translated file(s) into the workspace and:\n"
            f"{game_data}\n\n"
            "The game files will be replaced. Make a backup first if needed. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        import shutil

        self.files_dir.mkdir(exist_ok=True)
        game_data_path = Path(game_data)
        synced = 0
        exported = 0
        for name in exportable:
            src = translated_dir / name
            shutil.copy2(src, self.files_dir / name)
            synced += 1
            shutil.copy2(src, game_data_path / name)
            exported += 1

        self.refresh_file_lists()
        QMessageBox.information(
            self,
            "Sync & Export Complete",
            f"Synced {synced} file(s) to the workspace and exported "
            f"{exported} file(s) to:\n{game_data}",
        )

    def _export_active_files(self, filenames: list | None = None):
        """Export translated files into the game data folder.

        filenames: if provided, only those files are exported; otherwise all
        files currently in files/ are used (the original behavior, kept for
        back-compat and used by the Workflow tab via inheritance).
        """
        files_dir = Path("files")
        if filenames is not None:
            active = [n for n in filenames if n != ".gitkeep"]
        else:
            active = sorted(
                fp.name for fp in files_dir.glob("*.json") if fp.name != ".gitkeep"
            ) if files_dir.exists() else []

        if not active:
            QMessageBox.warning(self, "Export", "No files found in files/ — import game files first.")
            return

        # For RPG Maker MV/MZ, try to reuse the project path already set in the Workflow tab
        game_data = None
        module_text = ""
        try:
            module_text = self.module_combo.currentText().lower()
        except Exception:
            pass
        is_mvmz = "mv/mz" in module_text

        if is_mvmz:
            try:
                wt = self.window().workflow_tab
                if wt and getattr(wt, "_data_path", None):
                    game_data = wt._data_path
            except Exception:
                pass

        if not game_data:
            game_data = QFileDialog.getExistingDirectory(self, "Select Game Data Folder to Export Into")
            if not game_data:
                return

        transl_dir = Path("translated")
        exportable_count = sum(1 for name in active if (transl_dir / name).exists())
        reply = QMessageBox.question(
            self,
            "Export Active Files to Game",
            f"Export {exportable_count} file(s) into:\n{game_data}\n\nMake a backup first if needed. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        import shutil
        exported = 0
        skipped = 0
        for name in active:
            src = transl_dir / name
            if src.exists():
                shutil.copy2(src, Path(game_data) / name)
                exported += 1
            else:
                skipped += 1

        msg = f"Exported {exported} file(s) to:\n{game_data}"
        if skipped:
            msg += f"\n({skipped} file(s) not found in translated/ — skipped)"
        QMessageBox.information(self, "Export Complete", msg)

    def open_folder(self, folder_path):
        """Open a folder in the file explorer."""
        try:
            import platform
            if platform.system() == "Windows":
                subprocess.run(["explorer", str(folder_path)])
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", str(folder_path)])
            else:  # Linux
                subprocess.run(["xdg-open", str(folder_path)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open folder:\n{str(e)}")
    
    def _refresh_files_summary(self):
        """Update the Files-tab summary line from current row states."""
        if not hasattr(self, "progress_files_summary"):
            return
        items = getattr(self, "file_progress_items", {}) or {}
        total = len(items)
        if total == 0:
            self.progress_files_summary.setText("No files in this run.")
            return
        counts = {}
        for meta in items.values():
            st = (meta.get("status_text") or "Waiting").split(" ")[0]
            counts[st] = counts.get(st, 0) + 1
        parts = [f"{total} file(s)"]
        for key in (
            "Done", "Scanned", "Collected", "Writing", "Scanning", "Translating",
            "Failed", "Skipped", "Unsupported", "Waiting",
        ):
            if counts.get(key):
                parts.append(f"{counts[key]} {key.lower()}")
        self.progress_files_summary.setText(" · ".join(parts))

    def _set_progress_row(self, filename, *, status=None, status_color=None,
                          progress=None, tokens=None, cost=None, time_s=None):
        """Update one Files-tab table row."""
        meta = (getattr(self, "file_progress_items", {}) or {}).get(filename)
        if not meta:
            return
        row = meta.get("row")
        table = getattr(self, "progress_table", None)
        if table is None or row is None or row >= table.rowCount():
            return

        def _cell(col, text, color=None):
            item = table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                table.setItem(row, col, item)
            item.setText(str(text))
            if color:
                item.setForeground(QBrush(QColor(color)))

        if status is not None:
            meta["status_text"] = status
            _cell(1, status, status_color or "#cccccc")
        if progress is not None:
            _cell(2, progress, "#9cdcfe")
        if tokens is not None:
            _cell(3, tokens, "#f1c40f")
        if cost is not None:
            _cell(4, cost, "#4ec9b0")
        if time_s is not None:
            _cell(5, time_s, "#4da6ff")
        self._refresh_files_summary()

    def create_progress_item(self, filename):
        """Add a Files-tab table row for a file and return a placeholder shim."""
        table = getattr(self, "progress_table", None)
        if table is None:
            return _ShimWidget()

        row = table.rowCount()
        table.insertRow(row)
        values = [filename, "Waiting", "-", "-", "-", "-"]
        colors = ["#ffffff", "#888888", "#666666", "#666666", "#666666", "#666666"]
        for col, (val, color) in enumerate(zip(values, colors)):
            item = QTableWidgetItem(val)
            item.setForeground(QBrush(QColor(color)))
            if col == 0:
                item.setData(Qt.UserRole, filename)
            table.setItem(row, col, item)

        # Non-Qt shims keep older helpers working without spawning orphan windows.
        checkbox = _ShimCheckBox()
        checkbox.setEnabled(False)
        progress_label = _ShimLabel("Waiting...")
        progress_bar = _ShimProgressBar()
        tokens_label = _ShimLabel("")
        cost_label = _ShimLabel("")
        time_label = _ShimLabel("")
        status_label = _ShimLabel("")
        shim = _ShimWidget()

        self.file_progress_items[filename] = {
            "row": row,
            "status_text": "Waiting",
            "widget": shim,
            "checkbox": checkbox,
            "label": progress_label,
            "progress_bar": progress_bar,
            "tokens_label": tokens_label,
            "cost_label": cost_label,
            "time_label": time_label,
            "status_label": status_label,
        }
        self._refresh_files_summary()
        return shim

    def update_file_item_progress(self, filename, current, total):
        """Update progress for a specific file."""
        if filename not in self.file_progress_items:
            return
        item = self.file_progress_items[filename]
        try:
            item["progress_bar"].setMaximum(total if total > 0 else 100)
            item["progress_bar"].setValue(current)
            item["label"].setText(f"{current}/{total}")
        except Exception:
            pass
        phase = getattr(self, "_batch_ui_phase", None)
        parse_speakers = bool(
            getattr(getattr(self, "translation_worker", None), "parse_speakers", False)
        )
        if getattr(self, "_batch_active", False) and phase == "collect":
            status, color = "Scanning", "#007acc"
        elif getattr(self, "_batch_active", False) and phase == "consume":
            status, color = "Writing", "#007acc"
        elif parse_speakers:
            status, color = "Scanning", "#007acc"
        else:
            status, color = "Translating", "#007acc"
        self._set_progress_row(
            filename,
            status=status,
            status_color=color,
            progress=f"{current}/{total}" if total else "-",
        )

    def _apply_success_status_icon(self, item, completion_kind="normal"):
        """Mark a successful row; tooltips explain skip / idle / mismatch when relevant."""
        try:
            if completion_kind == "skip":
                reason = (item.get("_skip_reason") or "").strip()
                tip = f"Skipped: {reason}" if reason else "Whole file skipped (paths/fonts only)."
                status, color, glyph = "Skipped", "#dcdcaa", "✓"
            elif completion_kind == "idle":
                tip = "No translatable lines (non-dialogue content only)."
                status, color, glyph = "Done", "#4ec9b0", "✓"
            elif completion_kind == "mismatch":
                tip = (item.get("_mismatch_reason") or "").strip() or (
                    "Validation mismatch - original text kept for failed chunks."
                )
                status, color, glyph = "Mismatch", "#d4a017", "⚠"
            else:
                tip = ""
                status, color, glyph = "Done", "#4ec9b0", "✓"
            item["status_label"].setText(glyph)
            item["status_label"].setStyleSheet(
                f"color: {color}; font-weight: bold; font-size: "
                f"{'13px' if glyph == '⚠' else '11px'};"
            )
            item["status_label"].setToolTip(tip)
            item["status_label"].setVisible(True)
            for fname, meta in (getattr(self, "file_progress_items", {}) or {}).items():
                if meta is item:
                    self._set_progress_row(
                        fname, status=status, status_color=color, progress=glyph
                    )
                    break
        except Exception:
            pass

    def mark_file_complete(self, filename, success=True, error_message=None, completion_kind="normal"):
        """Mark a file as complete or failed."""
        if filename in self.file_progress_items:
            item = self.file_progress_items[filename]
            # If we have detailed result labels already set (via append_log),
            # show them and hide the progress bar to make room.
            if success:
                item['checkbox'].setChecked(True)
                if completion_kind == "mismatch" and error_message:
                    item["_mismatch_reason"] = error_message
                    item["_completion_kind"] = "mismatch"
                if item.get('tokens_label') and item['tokens_label'].text():
                    item['tokens_label'].setVisible(True)
                    item['cost_label'].setVisible(True)
                    item['time_label'].setVisible(True)
                    self._apply_success_status_icon(item, completion_kind)
                    try:
                        item['progress_bar'].setVisible(False)
                    except Exception:
                        pass
                    # Clear the transient progress text so completed rows don't show "x/y"
                    try:
                        item['label'].setText("")
                        item['label'].setStyleSheet("color: #888888; font-size: 11px;")
                    except Exception:
                        pass
                else:
                    # No parsed results available - show status in status_label
                    self._apply_success_status_icon(item, completion_kind)
                    try:
                        item['progress_bar'].setVisible(False)
                    except Exception:
                        pass
                    try:
                        item['label'].setText("")
                        item['label'].setStyleSheet("color: #888888; font-size: 11px;")
                    except Exception:
                        pass
            else:
                # Check if this is an unsupported file type error
                is_unsupported = False
                if error_message:
                    error_lower = error_message.lower()
                    is_unsupported = (
                        " not supported" in error_lower or
                        "not supported" == error_lower or
                        "unsupported" in error_lower or
                        "invalid file" in error_lower or
                        "wrong file type" in error_lower
                    )
                
                # Mark as failed - checkbox unchecked, red X or warning icon
                item['checkbox'].setChecked(False)
                try:
                    if is_unsupported:
                        item['status_label'].setText("⚠")
                        item['status_label'].setStyleSheet("color: #f1c40f; font-weight: bold; font-size: 13px;")
                        item['label'].setText("Not Supported")
                        self._set_progress_row(
                            filename,
                            status="Unsupported",
                            status_color="#f1c40f",
                            progress="-",
                        )
                    else:
                        item['status_label'].setText("✗")
                        item['status_label'].setStyleSheet("color: #f48771; font-weight: bold; font-size: 11px;")
                        item['label'].setText("Failed")
                        self._set_progress_row(
                            filename,
                            status="Failed",
                            status_color="#f48771",
                            progress="-",
                        )
                    item['status_label'].setVisible(True)
                    if error_message:
                        item['status_label'].setToolTip(f"Error: {error_message}")
                        item['widget'].setToolTip(f"Error: {error_message}")
                except Exception:
                    pass
                try:
                    item['progress_bar'].setVisible(False)
                except Exception:
                    pass
            # Always refresh table status for success paths that used the icon helper
            if success:
                tokens = item.get("tokens_label").text() if item.get("tokens_label") else ""
                cost = item.get("cost_label").text() if item.get("cost_label") else ""
                time_s = item.get("time_label").text() if item.get("time_label") else ""
                self._set_progress_row(
                    filename,
                    tokens=tokens or None,
                    cost=cost or None,
                    time_s=None if getattr(self, "_batch_active", False) else (time_s or None),
                )
    
    def reset_to_file_view(self):
        """Reset back to file selection view."""
        self._active_workflow_return = None
        self._reset_batch_pipeline_ui()
        self.file_stack.setCurrentIndex(0)
        if self.file_card.title_label is not None:
            self.file_card.title_label.setText("Files to translate")
        self.reset_view_button.setVisible(False)
        self.return_to_workflow_button.setVisible(False)
        # Also hide the open translations button when returning to file view
        try:
            self.open_translations_button.setVisible(False)
        except Exception:
            pass
        try:
            self.sync_export_button.setVisible(False)
        except Exception:
            pass
        # Hide totals when returning to file view
        try:
            if hasattr(self, 'totals_widget') and self.totals_widget:
                self.totals_widget.setVisible(False)
        except Exception:
            pass
        self.translate_button.setVisible(True)
        self.stop_button.setVisible(False)
        self.refresh_file_lists()
        self._on_mode_changed(self.mode_combo.currentText())
        self._set_run_controls_enabled(True)
        self._set_manual_context_controls_visible(
            self._pending_workflow_return is None
        )

    def set_workflow_return_target(self, workflow_tab):
        """Remember the workflow step that owns the next translation run."""
        step_index = None
        try:
            step_index = workflow_tab._step_tabs.currentIndex()
        except Exception:
            pass
        self._pending_workflow_return = (workflow_tab, step_index)
        self._set_manual_context_controls_visible(False)

    def _workflow_return_metadata(self):
        """Return a durable descriptor for the workflow that owns this run."""
        target = self._active_workflow_return or self._pending_workflow_return
        if target is None:
            return None
        workflow_tab, step_index = target
        parent = self.parent_window or self.window()
        wolf_tab = getattr(parent, "wolf_workflow_tab", None)
        engine = "wolfdawn" if workflow_tab is wolf_tab else "rpgmakermvmz"
        return {"engine": engine, "step_index": step_index}

    def _restore_batch_workflow_return(self, batch_metadata):
        """Restore a workflow return target saved with resumable batch state."""
        if self._active_workflow_return or self._pending_workflow_return:
            return
        descriptor = (batch_metadata or {}).get("workflow_return")
        if not isinstance(descriptor, dict):
            return
        engine = str(descriptor.get("engine") or "").strip().lower()
        if engine not in {"rpgmakermvmz", "wolfdawn"}:
            return
        step_index = descriptor.get("step_index")
        if step_index is not None and (
            not isinstance(step_index, int)
            or isinstance(step_index, bool)
            or step_index < 0
        ):
            return

        parent = self.parent_window or self.window()
        try:
            ensure_workflows = getattr(parent, "_ensure_workflow_container", None)
            if callable(ensure_workflows):
                ensure_workflows()
            attr = "wolf_workflow_tab" if engine == "wolfdawn" else "workflow_tab"
            workflow_tab = getattr(parent, attr, None)
            if workflow_tab is not None:
                self._pending_workflow_return = (workflow_tab, step_index)
                self._set_manual_context_controls_visible(False)
        except Exception:
            pass

    def _return_to_workflow(self):
        """Return to the exact workflow and step that launched this run."""
        target = self._active_workflow_return or self._pending_workflow_return
        if target is None:
            return
        workflow_tab, step_index = target
        parent = self.parent_window or self.window()

        self._active_workflow_return = None
        self._pending_workflow_return = None
        self.reset_to_file_view()

        try:
            workflow_stack = getattr(parent, "workflow_stack", None)
            if workflow_stack is not None:
                workflow_stack.setCurrentWidget(workflow_tab)
            engine_combo = getattr(parent, "workflow_engine_combo", None)
            if engine_combo is not None and workflow_stack is not None:
                engine_combo.setCurrentIndex(workflow_stack.currentIndex())
            if step_index is not None and hasattr(workflow_tab, "_goto_step"):
                workflow_tab._goto_step(step_index)
            if hasattr(parent, "switch_page"):
                parent.switch_page(getattr(parent, "PAGE_WORKFLOW", 1))
            elif hasattr(parent, "content_stack"):
                parent.content_stack.setCurrentIndex(1)
        except Exception:
            pass
            
    def start_translation(self, skip_confirm: bool = False, forced_resume_state: str | None = None):
        """Start the translation process.

        skip_confirm: when True the confirmation dialog is bypassed (used when
        called programmatically from the Workflow tab so the user doesn't need
        an extra click to confirm what they just explicitly requested).
        forced_resume_state: when set (from the Batch history tab), force Batch
        Translate mode and resume with this state without the Resume? dialog.
        """
        evaluation_tab = getattr(self.parent_window, "evaluation_tab", None)
        evaluation_worker = getattr(evaluation_tab, "_worker", None)
        if (
            evaluation_worker is not None
            and evaluation_worker.isRunning()
            and bool(getattr(
                evaluation_tab, "_worker_uses_translation_runtime", False
            ))
        ):
            QMessageBox.warning(
                self,
                "Evaluation preparation in progress",
                "Wait for evaluation preparation to finish before starting "
                "translation.",
            )
            return
        # Get checked files
        selected_files = self.get_selected_files()
        
        # Get selected module
        selected_index = self.module_combo.currentIndex()
        if selected_index < 0 or selected_index >= len(self.modules):
            QMessageBox.warning(self, "No Module", "Please select a translation module.")
            return
            
        selected_module = self.modules[selected_index]
        
        # Get mode from dropdown
        mode = self.mode_combo.currentText()
        if forced_resume_state:
            # Batch history Resume always runs Batch Translate.
            idx = self.mode_combo.findText(BATCH_MODE_LABEL)
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
            mode = BATCH_MODE_LABEL
        estimate_only = (mode == "Estimate")
        parse_speakers = (mode == "Parse Speakers")
        batch_mode = (mode == BATCH_MODE_LABEL)
        batch_resume_state = None
        batch_choice_confirmed = False
        batch_metadata = {}

        if batch_mode:
            load_dotenv()
            sys.path.insert(0, str(self.project_root))
            try:
                from util.translation import (
                    batchRunMetadata,
                    batchRunState,
                    isBatchSupported,
                )
            except Exception as e:
                QMessageBox.warning(self, "Batch Translate", f"Could not load batch support: {e}")
                return
            model = os.getenv("model", "")
            if not isBatchSupported(model):
                QMessageBox.warning(
                    self,
                    "Batch Translate",
                    "Batch Translate requires a supported native provider route: "
                    "Anthropic Claude, OpenAI GPT, or Google Gemini.\n\n"
                    "Custom OpenAI-compatible URLs are not assumed to implement a Batch API.",
                )
                return
            if forced_resume_state:
                batch_resume_state = forced_resume_state
            else:
                batch_resume_state = batchRunState()
                if batch_resume_state == "corrupt":
                    QMessageBox.critical(
                        self,
                        "Corrupt Batch Recovery",
                        "One or more batch recovery files are corrupt. The run was left "
                        "untouched and submission was blocked to prevent duplicate paid work.\n\n"
                        "Inspect log/batch_state.json, log/batch_requests.json (and "
                        "its .parts directory), and log/batch_results.json before "
                        "clearing the run.",
                    )
                    return
                if batch_resume_state:
                    if batch_resume_state == "queued":
                        prompt = (
                            "A saved batch is ready. Resume it?\n\n"
                            "Choose No to discard it and start over."
                        )
                    elif batch_resume_state == "fetched":
                        prompt = (
                            "A provider batch has finished and its results are ready "
                            "to write. Resume the write pass?\n\n"
                            "Choose No to discard those results and start over."
                        )
                    else:
                        prompt = (
                            "A batch is already in progress. Resume it?\n\n"
                            "Choosing No starts over and may duplicate provider charges."
                        )
                    reply = QMessageBox.question(
                        self,
                        "Resume batch?",
                        prompt,
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    batch_choice_confirmed = True
                    if reply != QMessageBox.Yes:
                        batch_resume_state = None

            if batch_resume_state:
                batch_metadata = batchRunMetadata()
                if batch_metadata.get("runtime_profile") is None:
                    from util.runtime_profile import (
                        capture_batch_runtime_profile,
                        is_rpgmaker_mvmz,
                    )

                    if is_rpgmaker_mvmz(selected_module[0]):
                        try:
                            current_profile = capture_batch_runtime_profile(
                                selected_module[0], self.project_root
                            )
                        except Exception as exc:
                            QMessageBox.warning(
                                self,
                                "Batch Profile Unavailable",
                                "Could not read the current RPG Maker code profile. "
                                "Resume was stopped before writing files.\n\n"
                                f"{exc}",
                            )
                            return
                        enabled_codes = sorted(
                            key
                            for key, enabled in (
                                (current_profile or {}).get("config", {}).items()
                            )
                            if key.startswith("CODE") and enabled is True
                        )
                        profile_summary = ", ".join(enabled_codes) or "no event codes"
                        reply = QMessageBox.question(
                            self,
                            "Confirm legacy batch profile",
                            "This batch was created before DazedTL saved its RPG Maker "
                            "code profile. To prevent another no-op write, confirm that "
                            "the current settings match the original collect pass.\n\n"
                            f"Currently enabled: {profile_summary}\n\n"
                            "Use these settings for this batch?",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No,
                        )
                        if reply != QMessageBox.Yes:
                            return
                        from util.translation import saveBatchRuntimeProfile

                        try:
                            saveBatchRuntimeProfile(current_profile)
                        except Exception as exc:
                            QMessageBox.warning(
                                self,
                                "Batch Profile Not Saved",
                                "Could not attach the confirmed code profile. Resume "
                                "was stopped before writing files.\n\n"
                                f"{exc}",
                            )
                            return
                        batch_metadata = batchRunMetadata()

                saved_files = list(batch_metadata.get("file_set") or [])
                if saved_files:
                    self.select_files_by_name(saved_files)
                    selected_files = self.get_selected_files()
                    missing_files = sorted(set(saved_files) - set(selected_files))
                    if missing_files:
                        preview = "\n".join(missing_files[:10])
                        if len(missing_files) > 10:
                            preview += f"\n… and {len(missing_files) - 10} more"
                        QMessageBox.warning(
                            self,
                            "Batch Files Missing",
                            "The original batch file set is no longer available. "
                            "Resume was stopped before consuming results:\n\n" + preview,
                        )
                        return

        if not selected_files:
            QMessageBox.warning(
                self,
                "No Files Selected",
                "Please check at least one file to translate.",
            )
            return
        
        # Confirm start (skipped when called programmatically from the Workflow tab
        # or when Batch history already confirmed Resume).
        if not skip_confirm and not forced_resume_state and not batch_choice_confirmed:
            if batch_mode and not batch_resume_state:
                reply = QMessageBox.question(
                    self,
                    "Start Batch Translate",
                    f"Start batch translation for {len(selected_files)} file(s) using {selected_module[0]}?\n\n"
                    "Pass 1 collects dialogue for the batch; you confirm the estimate, then the provider "
                    "processes it (typically 50% off). Pass 2 writes translated files.\n\n"
                    f"⚠ {BATCH_COLLECT_LIVE_CHARGE_NOTE}",
                    QMessageBox.Yes | QMessageBox.No,
                )
            else:
                action = mode.lower()
                reply = QMessageBox.question(
                    self,
                    f"Start {mode}",
                    f"Start {action} for {len(selected_files)} file(s) using {selected_module[0]}?",
                    QMessageBox.Yes | QMessageBox.No,
                )
            if reply != QMessageBox.Yes:
                return

        if batch_resume_state:
            self._restore_batch_workflow_return(batch_metadata)
        # Translation can start without opening the lazily-created Workflow.
        # Workflow roots retain engine validation; an explicitly selected
        # generic context may use an unfamiliar project structure.
        workflow_launch = self._pending_workflow_return is not None
        try:
            if workflow_launch or not self._manual_context_root:
                _activate_configured_game_context(self.settings, selected_module[0])
            else:
                _activate_game_context_root(
                    self._manual_context_root,
                    selected_module[0],
                    validate_engine=False,
                )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Game Translation Settings",
                f"Could not load the selected translation settings:\n\n{exc}",
            )
            return

        self._active_workflow_return = self._pending_workflow_return
        self._pending_workflow_return = None
        
        if True:
            # Switch to progress view
            self.file_stack.setCurrentIndex(1)
            if self.file_card.title_label is not None:
                self.file_card.title_label.setText("Translation progress")
            self._set_activity_visible(True)
            self._set_run_controls_enabled(False)
            
            # Initialize Files-tab table with all selected files
            self.progress_list.clear()
            self.file_progress_items.clear()
            if hasattr(self, "progress_table"):
                self.progress_table.setRowCount(0)
            if hasattr(self, "progress_files_summary"):
                self.progress_files_summary.setText("No files in this run.")

            for filename in selected_files:
                self.create_progress_item(filename)
            
            # Toggle button visibility
            self.translate_button.setVisible(True)
            self.translate_button.setEnabled(False)
            self.translate_button.setText("Run in progress…")
            if batch_mode:
                # Shown during collect; hidden once collection finishes (see _on_batch_phase)
                self.stop_button.setVisible(batch_resume_state is None)
            else:
                self.stop_button.setVisible(True)
            # Show totals footer and reset totals when starting translation
            try:
                self.totals_input_tokens = 0
                self.totals_output_tokens = 0
                self.totals_cost = 0.0
                self.totals_time = 0.0
                # Reset seen filenames for this run so totals can be applied anew
                try:
                    self._applied_file_totals.clear()
                except Exception:
                    self._applied_file_totals = set()
                if hasattr(self, 'totals_tokens_label'):
                    self.totals_tokens_label.setText("Tokens: 0 in / 0 out")
                if hasattr(self, 'totals_cost_label'):
                    self.totals_cost_label.setText("Cost: $0.0000")
                if hasattr(self, 'totals_time_label'):
                    self.totals_time_label.setText("Time: 0.0s")
                if hasattr(self, 'totals_mismatch_label'):
                    self.totals_mismatch_label.setText("")
                    self.totals_mismatch_label.setVisible(False)
                self.totals_mismatch_count = 0
                if hasattr(self, 'totals_widget') and self.totals_widget:
                    self.totals_widget.setVisible(True)
            except Exception:
                pass
            # Hide all post-run buttons while a new run is in progress
            for _btn_attr in (
                "open_translations_button",
                "reset_view_button",
                "return_to_workflow_button",
                "sync_export_button",
            ):
                try:
                    getattr(self, _btn_attr).setVisible(False)
                except Exception:
                    pass
            
            # Initialize progress tracking
            self.files_completed = 0
            self.files_total = len(selected_files)
            self._file_progress_started = False
            self._batch_active = batch_mode
            self._batch_ui_phase = None
            self._batch_consume_started = False
            self._finish_pending = None
            if batch_mode:
                self._set_progress_view_mode(True, len(selected_files))
                self.batch_overall_bar.setFormat("%p%")
                self.batch_overall_bar.setValue(0)
                self.batch_pipeline_stack.setCurrentIndex(0)
                self.batch_live_status.setText("")
                # Resume-from-fetched jumps straight to write; arm the UI before the
                # worker starts so early cost lines are not dropped as "pre-consume".
                if batch_resume_state == "fetched":
                    self._on_batch_phase("consume", None)
            else:
                self._set_progress_view_mode(False, len(selected_files))
                self._batch_active = False
                self._batch_ui_phase = None
                self._batch_consume_started = False
            self.files_translated_label.setText(f"0/{self.files_total}")
            self.translating_label.setText("Starting...")
            self.item_progress_label.setText("0/0")
            self.item_progress_bar.setValue(0)
            self.item_progress_bar.setMaximum(100)
            
            # Remember which files this run covers so the post-run export button
            # can export exactly those files rather than all active files.
            self._last_run_files = list(selected_files)

            # Create and start translation worker
            self.translation_worker = TranslationWorker(
                self.project_root, 
                selected_module, 
                estimate_only,
                selected_files,
                parse_speakers=parse_speakers,
                batch_mode=batch_mode,
                batch_resume_state=batch_resume_state,
                batch_workflow_return=self._workflow_return_metadata(),
            )
            
            # Connect signals
            self.translation_worker.log_signal.connect(self.append_log)
            self.translation_worker.progress_signal.connect(self.update_file_progress)
            self.translation_worker.item_progress_signal.connect(self.update_item_progress)
            self.translation_worker.status_signal.connect(self.translating_label.setText)
            self.translation_worker.file_error_signal.connect(self.on_file_error)
            self.translation_worker.file_mismatch_signal.connect(self.on_file_mismatch)
            self.translation_worker.finished_signal.connect(self.on_translation_finished)
            self.translation_worker.batch_phase_signal.connect(self._on_batch_phase)
            self.translation_worker.speaker_confirmation_signal.connect(
                self._on_speaker_confirmation
            )
            # Prepare a per-run log file in log/history and start tailing it so
            # the right-hand log panel shows only this run's new lines.
            try:
                history_dir = self.project_root / 'log' / 'history'
                history_dir.mkdir(parents=True, exist_ok=True)
                
                # Clean up old log files, keeping only the 10 most recent
                try:
                    log_files = sorted(history_dir.glob("translationHistory_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
                    # Keep only the 10 most recent, delete the rest
                    for old_log in log_files[10:]:
                        try:
                            old_log.unlink()
                        except Exception:
                            pass
                except Exception:
                    pass
                
                # Use timestamp (safe filename) for sorting
                fname = datetime.datetime.now().strftime('translationHistory_%Y%m%d_%H%M%S.txt')
                run_log_path = history_dir / fname
                # Don't create the file yet - it will be created when first log is written
                
                # Create the per-run log immediately with a header so the Translation
                # Log panel is never blank while a batch resume/consume runs.
                try:
                    mode = BATCH_MODE_LABEL if batch_mode else mode
                    with open(run_log_path, "a", encoding="utf-8") as f:
                        f.write(
                            f"[RUN] {mode}"
                            + (f" resume={batch_resume_state}" if batch_resume_state else "")
                            + f" files={len(selected_files)}\n"
                        )
                        for name in selected_files:
                            f.write(f"[RUN]   - {name}\n")
                        f.flush()
                except Exception:
                    pass

                # Export env var so subprocess workers inherit the path
                try:
                    os.environ['TRANSLATION_RUN_LOG'] = str(run_log_path)
                except Exception:
                    pass

                # Try to create a hard link at legacy location so modules that
                # still write to log/translationHistory.txt end up in this file.
                # This will be created when the run_log_path file is first written to
                legacy = self.project_root / 'log' / 'translationHistory.txt'
                try:
                    # Remove any existing legacy file
                    if legacy.exists():
                        try:
                            legacy.unlink()
                        except Exception:
                            pass
                except Exception:
                    pass

                # Clear UI log and start tailing the per-run file (tailer will handle non-existent files)
                self.translation_log_viewer.clear_log()
                self.translation_log_viewer.start_tail(run_log_path)
            except Exception:
                # Fallback to legacy file if anything goes wrong
                try:
                    self.translation_log_viewer.clear_log()
                    self.translation_log_viewer.start_tail(self.project_root / 'log' / 'translationHistory.txt')
                except Exception:
                    pass

            # Start the worker
            self.translation_worker.start()
            
    def append_log(self, message):
        # Detect mismatch markers emitted to stdout by translation.py.
        # This is the primary, non-racy detection path for subprocess mode.
        if isinstance(message, str) and message.startswith("MISMATCH_EVENT:"):
            self.on_mismatch_detected()
            return  # marker is internal, not displayed
        # During batch collect/poll/submit, per-file cost lines are not final translations.
        # Accept costs once consume has started (and after done) - resume→consume is fast
        # enough that log lines from the pool thread can arrive before/after the phase
        # signal is processed on the UI thread.
        if getattr(self, "_batch_active", False):
            phase = getattr(self, "_batch_ui_phase", None)
            consume_started = getattr(self, "_batch_consume_started", False)
            if not consume_started and phase not in ("consume", "done"):
                return
        try:
            stripped = _strip_ansi(message)
            pattern = (
                r'^\s*(?P<filename>[^:]+):.*?\[Input:\s*(?P<input>\d+)\].*?\[Output:\s*(?P<output>\d+)\]'
                r'.*?\[Cost:\s*\$(?P<cost>[\d,\.]+)\].*?\[(?P<time>[\d\.]+)s\]'
            )
            m = re.search(pattern, stripped)
            if not m:
                return
            filename = m.group("filename").strip()
            if filename.lower() == "total":
                return
            input_tokens = int(m.group("input"))
            output_tokens = int(m.group("output"))
            cost = float(m.group("cost").replace(",", ""))
            time_s = float(m.group("time"))
            m_skip = re.search(r"\[skipped\]\s*(.*)$", stripped)
            skip_reason = (m_skip.group(1) or "").strip() if m_skip else ""
            if skip_reason:
                completion_kind = "skip"
            elif input_tokens == 0 and output_tokens == 0:
                completion_kind = "idle"
            else:
                completion_kind = "normal"
            existing = (self.file_progress_items.get(filename) or {}).get(
                "_completion_kind"
            )
            if existing == "mismatch" and completion_kind == "normal":
                completion_kind = "mismatch"
            self._apply_file_result(
                filename,
                input_tokens,
                output_tokens,
                cost,
                time_s,
                completion_kind=completion_kind,
                skip_reason=skip_reason,
            )
        except Exception:
            # Ignore parse/logging errors
            pass
        # Do not forward this message into the LogViewer (we tail the log file separately).
        return

    def _apply_file_result(
        self,
        filename,
        input_tokens,
        output_tokens,
        cost,
        time_s,
        completion_kind="normal",
        skip_reason="",
    ):
        """Update a file's item UI with parsed result details and update totals."""
        # Update per-item display
        if filename in self.file_progress_items:
            item = self.file_progress_items[filename]
            try:
                item.pop("_skip_reason", None)
                if skip_reason:
                    item["_skip_reason"] = skip_reason
                # Distinguish "no API usage" from real token counts in the list UI
                if completion_kind in ("skip", "idle"):
                    tokens_text = "-"
                else:
                    tokens_text = f"{input_tokens}/{output_tokens}"
                cost_text = f"${cost:.4f}"
                time_text = f"{time_s:.1f}s"
                item["tokens_label"].setText(tokens_text)
                item['cost_label'].setText(cost_text)
                item['time_label'].setText(time_text)
                item['tokens_label'].setVisible(True)
                item['cost_label'].setVisible(True)
                item['time_label'].setVisible(True)
                try:
                    item['progress_bar'].setVisible(False)
                except Exception:
                    pass
                self._set_progress_row(
                    filename,
                    tokens=tokens_text,
                    cost=cost_text,
                    time_s=None if getattr(self, "_batch_active", False) else time_text,
                )
            except Exception:
                pass

        try:
            if not hasattr(self, '_applied_file_totals'):
                self._applied_file_totals = set()
            if filename not in self._applied_file_totals:
                self._applied_file_totals.add(filename)
                self.totals_input_tokens += int(input_tokens)
                self.totals_output_tokens += int(output_tokens)
                self.totals_cost += float(cost)
            # Total time should be the longest single-file time (not the sum)
            self.totals_time = max(self.totals_time, float(time_s))
            # Refresh totals labels
            if hasattr(self, 'totals_tokens_label'):
                self.totals_tokens_label.setText(f"Tokens: {self.totals_input_tokens} in / {self.totals_output_tokens} out")
            if hasattr(self, 'totals_cost_label'):
                self.totals_cost_label.setText(f"Cost: ${self.totals_cost:.4f}")
            if hasattr(self, 'totals_time_label'):
                self.totals_time_label.setText(f"Time: {self.totals_time:.1f}s")
        except Exception:
            pass
        # Mark file as complete (this will ensure checkbox and label updated)
        try:
            self.mark_file_complete(filename, success=True, completion_kind=completion_kind)
        except Exception:
            pass
    
    def update_file_progress(self, current_file, total_files, filename):
        """Update the file-level progress."""
        self._file_progress_started = True
        batch_active = getattr(self, "_batch_active", False)
        phase = getattr(self, "_batch_ui_phase", None) if batch_active else None
        parse_speakers = bool(
            getattr(getattr(self, "translation_worker", None), "parse_speakers", False)
        )

        if batch_active:
            if phase == "collect":
                self.files_completed = current_file
                self.files_translated_label.setText(f"{current_file}/{total_files} collected")
                self.batch_collect_status.setText(
                    f"Pass 1/2: collecting {current_file}/{total_files} files…"
                )
                self.batch_live_status.setText(f"Current file: {filename}")
                self.batch_overall_bar.setValue(15 + int(20 * current_file / max(total_files, 1)))
                self.mark_file_queued(filename)
                return
            if phase in (
                "collect_done", "submit", "canceled", "no_work",
                "polling", "poll_status", "failed",
            ):
                # A collect-pass progress event can arrive after the phase has
                # advanced. Count it, but never promote its row to translated.
                self.files_completed = current_file
                if phase == "no_work":
                    self.files_translated_label.setText(
                        f"{current_file}/{total_files} scanned"
                    )
                    self._mark_batch_files_no_work()
                try:
                    if self._finish_pending and self.files_completed >= self.files_total:
                        success, message = self._finish_pending
                        self._finish_pending = None
                        self._apply_finish_ui(success, message)
                except Exception:
                    pass
                return

        self.files_completed = current_file
        if parse_speakers:
            self.files_translated_label.setText(f"{current_file}/{total_files} scanned")
        else:
            self.files_translated_label.setText(f"{current_file}/{total_files}")

        # Row details (tokens/cost) come from parsed stdout via append_log. If that
        # did not run (older modules / parse miss), finalize so the row is not stuck.
        if filename in self.file_progress_items:
            if parse_speakers:
                # Harvest only - translation of nameplates happens after all files.
                self.mark_file_queued(filename)
                meta = self.file_progress_items[filename]
                try:
                    meta["label"].setText("Scanned")
                except Exception:
                    pass
                self._set_progress_row(
                    filename,
                    status="Scanned",
                    status_color="#d4a017",
                    progress="names",
                )
            else:
                sl = self.file_progress_items[filename].get("status_label")
                if not sl or not sl.text():
                    self.mark_file_complete(filename, success=True)

        # Clear current_translating_file if it was the same file
        if self.current_translating_file == filename:
            self.current_translating_file = None

        # Update the top-level translating label: if there are more files
        # remaining, keep it as a generic "Translating..." until the next
        # file emits item-level progress (which will set the actual
        # filename). If this was the final file, show a neutral state.
        if batch_active and phase == "consume":
            self.batch_overall_bar.setValue(80 + int(15 * current_file / max(total_files, 1)))
            self.batch_consume_status.setText(
                f"Pass 2/2: writing translations ({current_file}/{total_files})…"
            )
            self.batch_live_status.setText(f"Current file: {filename}")
        if current_file < total_files:
            self.translating_label.setText(
                "Scanning speakers..." if parse_speakers else "Translating..."
            )
        else:
            if batch_active and phase == "consume":
                self.translating_label.setText("Finishing batch…")
            elif parse_speakers:
                # Keep a clear post-scan state until status_signal / finished.
                self.translating_label.setText("Translating speakers…")
            else:
                self.translating_label.setText("—")
    
        # If the translation worker already signaled finished but we
        # hadn't yet shown the final UI (because the worker finished
        # before this last progress update), apply the pending finish
        # now that all files have reported completion.
        try:
            if self._finish_pending and self.files_completed >= self.files_total:
                success, message = self._finish_pending
                self._finish_pending = None
                # Finalize UI now
                self._apply_finish_ui(success, message)
        except Exception:
            pass

    def update_item_progress(self, filename, current_item, total_items):
        """Update the item-level progress (from tqdm)."""
        batch_active = getattr(self, "_batch_active", False)
        phase = getattr(self, "_batch_ui_phase", None) if batch_active else None

        self.item_progress_label.setText(f"{current_item}/{total_items}")
        self.item_progress_bar.setMaximum(total_items if total_items > 0 else 100)
        self.item_progress_bar.setValue(current_item)
        self.translating_label.setText(filename)
        
        if filename in self.file_progress_items:
            self.update_file_item_progress(filename, current_item, total_items)
            label = self.file_progress_items[filename]['label']
            if label.text() in ("Waiting...", "Queued"):
                if batch_active and phase == "collect":
                    label.setText("Scanning...")
                else:
                    label.setText("Translating...")
                label.setStyleSheet("color: #007acc; font-weight: bold;")
    
    def on_file_error(self, filename, error_message):
        """Handle a file translation error."""
        # Mark the file as failed with the error message
        self.mark_file_complete(filename, success=False, error_message=error_message)

    def on_file_mismatch(self, filename, error_message):
        """Soft validation failure: keep written output, mark the file for review."""
        self.mark_file_complete(
            filename,
            success=True,
            error_message=error_message,
            completion_kind="mismatch",
        )

    def on_mismatch_detected(self):
        """Increment the mismatch counter and update the totals label."""
        try:
            if not hasattr(self, 'totals_mismatch_count'):
                self.totals_mismatch_count = 0
            self.totals_mismatch_count += 1
            if hasattr(self, 'totals_mismatch_label'):
                self.totals_mismatch_label.setText(
                    f"Validation warnings: {self.totals_mismatch_count} "
                    f"{'chunk' if self.totals_mismatch_count == 1 else 'chunks'} "
                    "kept original text"
                )
                self.totals_mismatch_label.setVisible(True)
        except Exception:
            pass
            
    def flush_log_buffer(self):
        """No longer needed - kept for compatibility."""
        self.log_buffer.clear()
        self.log_timer.stop()
        
    def update_progress(self, current_file, total_files, filename):
        """Legacy method - redirect to new method."""
        self.update_file_progress(current_file, total_files, filename)
        
    def on_translation_finished(self, success, message):
        """Handle translation completion."""
        # Mark the last file as complete if needed
        if self.current_translating_file:
            self.mark_file_complete(self.current_translating_file, success=success)

        # If not all files have reported completion yet, defer final UI
        # changes until the final file progress update arrives. This
        # prevents the back/reset button from showing prematurely.
        try:
            if (
                getattr(self, "_file_progress_started", False)
                and self.files_total
                and self.files_completed < self.files_total
            ):
                self._finish_pending = (success, message)
                return
        except Exception:
            # If anything goes wrong with counts, fall through and finalize.
            pass

        # Otherwise finalize immediately
        self._apply_finish_ui(success, message)

    def _apply_finish_ui(self, success, message):
        """Apply UI changes for a finished translation run."""
        if self.file_card.title_label is not None:
            self.file_card.title_label.setText("Translation results")
        if getattr(self, "_batch_active", False):
            phase = getattr(self, "_batch_ui_phase", None)
            mismatch_count = max(
                0,
                int(
                    getattr(
                        getattr(self, "translation_worker", None),
                        "_run_mismatch_count",
                        getattr(self, "_batch_mismatch_count", 0),
                    )
                    or 0
                ),
            )
            if success and phase == "canceled":
                self.reset_to_file_view()
                try:
                    if hasattr(self, 'translation_log_viewer') and self.translation_log_viewer:
                        QTimer.singleShot(600, self.translation_log_viewer.stop_tail)
                except Exception:
                    pass
                return
            if success and phase not in ("no_work", "canceled"):
                self._on_batch_phase("done", {"mismatches": mismatch_count})
            elif not success and message != "Batch polling stopped":
                self._on_batch_phase("failed", {"message": message})
        # Parse Speakers: promote Scanned rows to Done only after vocab write finishes,
        # then leave the next run in normal translation mode. Otherwise the mode
        # remains sticky and pressing Start again silently repeats speaker collection.
        try:
            worker = getattr(self, "translation_worker", None)
            if success and worker and getattr(worker, "parse_speakers", False):
                for fname, meta in (getattr(self, "file_progress_items", {}) or {}).items():
                    if (meta.get("status_text") or "") == "Scanned":
                        self.mark_file_complete(fname, success=True)
                translate_index = self.mode_combo.findText("Translate")
                if translate_index >= 0:
                    self.mode_combo.setCurrentIndex(translate_index)
        except Exception:
            pass
        workflow_run = self._active_workflow_return is not None

        # Workflow runs have a single, dominant next action: return to the step
        # that launched them. Standalone runs keep the normal result actions.
        try:
            self.stop_button.setVisible(False)
        except Exception:
            pass
        try:
            self.return_to_workflow_button.setVisible(workflow_run)
            self.reset_view_button.setVisible(not workflow_run)
        except Exception:
            pass

        try:
            self.open_translations_button.setVisible(not workflow_run)
        except Exception:
            pass

        # Every RPG Maker run offers one action that keeps the workspace and
        # exported game data in sync, including runs launched from a workflow.
        try:
            module_text = self.module_combo.currentText().lower()
            is_rpgmaker = "rpg maker" in module_text or "rpgmaker" in module_text
            self.sync_export_button.setVisible(is_rpgmaker)
        except Exception:
            pass

        # Update progress display
        try:
            batch_phase = getattr(self, "_batch_ui_phase", None)
            if success and batch_phase == "no_work":
                self.translating_label.setText("No eligible text found")
                self.translate_button.setText("Nothing to submit")
            elif success:
                mismatch_count = max(
                    0,
                    int(
                        getattr(
                            getattr(self, "translation_worker", None),
                            "_run_mismatch_count",
                            getattr(self, "_batch_mismatch_count", 0),
                        ) or 0
                    ),
                )
                if mismatch_count:
                    self.translating_label.setText("Completed with warnings")
                    self.translate_button.setText("Completed with warnings")
                else:
                    self.translating_label.setText("Completed!")
                    self.translate_button.setText("Run complete")
            else:
                self.translating_label.setText(f"Failed: {message}")
                self.translate_button.setText("Run failed")
            self.translate_button.setEnabled(False)
            self.translate_button.setVisible(not workflow_run)
        except Exception:
            pass

        # Refresh file list to show any new translated files
        try:
            self.refresh_file_lists()
        except Exception:
            pass

        # Stop tailing the log after a short delay so the final poll
        # can pick up any data written just before the worker finished.
        try:
            if hasattr(self, 'translation_log_viewer') and self.translation_log_viewer:
                QTimer.singleShot(600, self.translation_log_viewer.stop_tail)
        except Exception:
            pass
            
    def stop_translation(self):
        """Stop the translation process."""
        if hasattr(self, 'translation_worker') and self.translation_worker.isRunning():
            self.translation_worker.stop()
            
            # Wait for the worker to stop gracefully
            if not self.translation_worker.wait(5000):  # Wait up to 5 seconds
                self.translation_worker.terminate()
                self.translation_worker.wait(2000)  # Wait for termination
        
        # Toggle button visibility
        self.translate_button.setVisible(True)
        self.translate_button.setEnabled(False)
        self.stop_button.setVisible(False)
        # If a finish was pending (worker signaled finished before
        # file progress completed), clear it and finalize UI now since
        # the user requested a stop and no further progress updates
        # are expected.
        try:
            self._finish_pending = None
        except Exception:
            pass

        try:
            # Apply final UI for stopped run
            self._apply_finish_ui(False, "Translation stopped by user")
        except Exception:
            pass
        self.translating_label.setText("Stopped")
        self.translate_button.setText("Run stopped")
        
    def closeEvent(self, event):
        """Handle widget close event."""
        if hasattr(self, 'log_timer'):
            self.log_timer.stop()
        if hasattr(self, 'translation_log_viewer') and self.translation_log_viewer:
            self.translation_log_viewer.stop_tail(drain=False)
        event.accept()
