#!/usr/bin/env python3
"""
Rewrite Tab for DazedMTLTool GUI

Fixes over-limit game dialogue via LLM API.
Scans translated/*.json for messages exceeding 3 lines / 60 chars per line,
then rewrites them via the configured LLM while preserving all meaning.
"""

import os
import json
import time
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dotenv import load_dotenv

# Optional fast token counter — falls back to char/4 heuristic if unavailable
try:
    import tiktoken as _tiktoken
    _TIKTOKEN_OK = True
except ImportError:
    _TIKTOKEN_OK = False

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox,
    QTextEdit, QMessageBox, QListWidget, QListWidgetItem,
    QSplitter, QFileDialog, QProgressBar, QFrame, QSpinBox, QLineEdit,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QMutex
from PyQt5.QtGui import QFont, QColor


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_LINES = 3
MAX_LINE_LEN = 60
NEWLINE = "\r\n"

SYSTEM_PROMPT_TEMPLATE = """\
You are an editor for a visual novel translation. Rewrite dialogue so it fits
the game's text box.

Hard limits (non-negotiable):
- Maximum 3 lines
- Maximum 60 characters per line (every character counts)
- Break lines on spaces only — never mid-word
- Put each line on its own line (use a newline character to separate lines)

Rewriting rules:
1. Preserve ALL meaning — every fact and clause must survive in condensed form
2. NEVER truncate — do not drop the last sentence or clause to make it fit;
   rephrase earlier parts more tightly instead
3. If a line ends a sentence, the next line begins with a capital letter
4. Preserve these terms exactly: {terms}
5. Use only plain ASCII punctuation — NO em dashes (—), en dashes (–),
   ellipsis (…), or curly quotes. Use a hyphen (-) instead of a dash.

Reply with ONLY the rewritten text, each line on its own line.
No explanation, no quotes, no markdown."""

DEFAULT_TERMS = (
    "Settler, Assimilation, Synchronization, Those Things, We, Inspector, "
    "Suppressant, Brain Dive, Mutant Form, Mimicry, Resource War, "
    "Resource Crisis, Quarantine, Debris Field"
)

USER_PROMPT_TEMPLATE = """\
Rewrite this to fit in 3 lines of max 60 characters each.
Keep all meaning. Do not drop the ending.

Original:
{original_flat}"""

RETRY_PROMPT_TEMPLATE = """\
VALIDATION FAILED: {issues}

Rewrite more tightly. Every character counts — including spaces and punctuation.
Do NOT drop any meaning from the original. Rephrase earlier parts to make room."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_violation(text: str) -> bool:
    lines = text.split(NEWLINE)
    if len(lines) > MAX_LINES:
        return True
    return any(len(line) > MAX_LINE_LEN for line in lines)


def is_valid(text: str) -> list:
    issues = []
    lines = text.split("\r\n")
    if len(lines) > 3:
        issues.append(f"{len(lines)} lines (max 3)")
    for i, line in enumerate(lines, 1):
        if len(line) > 60:
            issues.append(f"line {i} is {len(line)} chars (max 60)")
    return issues


def scan_folder(folder: Path) -> list:
    violations = []
    for f in sorted(folder.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for i, entry in enumerate(data):
            if not isinstance(entry, dict):
                continue
            m = entry.get("message")
            if isinstance(m, str) and is_violation(m):
                violations.append({"file": f.name, "index": i, "original": m})
    return violations


def load_vocab_terms(project_root: Path) -> str:
    """Load preserved terms from vocab.txt if present, else use defaults."""
    vocab_path = project_root / "vocab.txt"
    if vocab_path.exists():
        try:
            lines = [ln.strip() for ln in vocab_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if lines:
                return ", ".join(lines)
        except Exception:
            pass
    return DEFAULT_TERMS


# ---------------------------------------------------------------------------
# Cost estimation helpers
# ---------------------------------------------------------------------------

# Approximate output tokens per rewrite (used for pre-run estimate)
_EST_OUTPUT_TOKENS = 150


def _count_tokens(text: str, model: str) -> int:
    """Fast token count using tiktoken; falls back to char/4 heuristic."""
    if _TIKTOKEN_OK:
        try:
            enc = _tiktoken.encoding_for_model(model)
        except Exception:
            try:
                enc = _tiktoken.get_encoding("cl100k_base")
            except Exception:
                return len(text) // 4
        return len(enc.encode(text))
    return len(text) // 4


def estimate_run_cost(violations: list, project_root: Path) -> str:
    """Return a human-readable cost estimate for a full rewrite run."""
    try:
        load_dotenv()
        model = os.getenv("model", "gpt-4.1").strip()
        from util.translation import getPricingConfig
        pricing = getPricingConfig(model)
        in_rate  = pricing["inputAPICost"]   # $ per million tokens
        out_rate = pricing["outputAPICost"]

        terms = load_vocab_terms(project_root)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(terms=terms)
        sys_tokens = _count_tokens(system_prompt, model)

        total_in = 0
        total_out = 0
        for v in violations:
            original_flat = v["original"].replace(NEWLINE, "\n")
            user_msg = USER_PROMPT_TEMPLATE.format(original_flat=original_flat)
            total_in  += sys_tokens + _count_tokens(user_msg, model)
            total_out += _EST_OUTPUT_TOKENS

        cost = (total_in / 1_000_000) * in_rate + (total_out / 1_000_000) * out_rate
        return (
            f"~${cost:.4f}  "
            f"({total_in:,} in / ~{total_out:,} out est.  |  "
            f"${in_rate:.2f}/${out_rate:.2f} per M)"
        )
    except Exception as exc:
        return f"(estimate unavailable: {exc})"


# ---------------------------------------------------------------------------
# API caller (OpenAI-compat + Anthropic)
# ---------------------------------------------------------------------------

def _normalise_line_endings(text: str) -> str:
    """Normalise any line-ending variant the LLM might emit to actual \\r\\n."""
    # Handle escaped sequences the model may output literally (e.g. backslash-r-backslash-n)
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n")
    # Now normalise all real CR/LF variants
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "\r\n")


# Characters the game engine cannot render — map to ASCII-safe equivalents
_CHAR_SUBSTITUTIONS = [
    ("\u2014", " - "),   # em dash  —  →  hyphen
    ("\u2013", " - "),   # en dash  –  →  hyphen
    ("\u2026", "..."),   # ellipsis …  →  three dots
    ("\u201C", '"'),     # left double quote  "
    ("\u201D", '"'),     # right double quote "
    ("\u2018", "'"),     # left single quote  '
    ("\u2019", "'"),     # right single quote '
]


def _sanitise_output(text: str) -> str:
    """Replace characters the game engine can't render with ASCII equivalents."""
    for src, dst in _CHAR_SUBSTITUTIONS:
        text = text.replace(src, dst)
    return text


def _extract_claude_text(response) -> str:
    """Collect text from all text blocks; skip thinking/tool blocks."""
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            t = getattr(block, "text", None)
            if t:
                parts.append(t)
        elif hasattr(block, "text") and block.text:
            # Older SDK blocks without explicit type
            parts.append(block.text)
    text = "".join(parts).strip()
    if not text:
        stop = getattr(response, "stop_reason", None)
        raise ValueError(
            f"Empty response from API (stop_reason={stop!r}). "
            "Try again or use a different model."
        )
    return text


def _extract_openai_text(response) -> str:
    """Extract assistant message text from an OpenAI-compatible completion."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ValueError("Empty response from API (no choices returned).")
    message = choices[0].message
    text = getattr(message, "content", None)
    if text is None and hasattr(message, "refusal") and message.refusal:
        raise ValueError(f"Model refused: {message.refusal}")
    if not text or not str(text).strip():
        finish = getattr(choices[0], "finish_reason", None)
        raise ValueError(
            f"Empty response from API (finish_reason={finish!r}). "
            "Try again or use a different model."
        )
    return str(text).strip()


def _call_llm(messages: list, model: str, api_url: str, api_key: str,
              is_claude: bool, timeout: int) -> tuple:
    """Call the LLM. Returns (text, input_tokens, output_tokens)."""
    if is_claude:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        system_text = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=system_text,
            messages=user_msgs,
            timeout=timeout,
        )
        text = _extract_claude_text(response)
        in_tok = getattr(response.usage, "input_tokens", 0) or 0
        out_tok = getattr(response.usage, "output_tokens", 0) or 0
        return text, in_tok, out_tok
    else:
        import openai as _openai
        client_kwargs = {"api_key": api_key}
        if api_url:
            client_kwargs["base_url"] = api_url
        client = _openai.OpenAI(**client_kwargs)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=512,
            temperature=0,
            timeout=timeout,
        )
        text = _extract_openai_text(response)
        in_tok = getattr(response.usage, "prompt_tokens", 0) or 0
        out_tok = getattr(response.usage, "completion_tokens", 0) or 0
        return text, in_tok, out_tok


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class RewriteWorker(QThread):
    log_signal = pyqtSignal(str)
    file_status_signal = pyqtSignal(str, str)           # filename, status
    progress_signal = pyqtSignal(int, int)              # current, total
    cost_signal = pyqtSignal(float, int, int)           # running_cost, total_in_tok, total_out_tok
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, violations: list, output_folder: Path, max_retries: int,
                 file_threads: int, project_root: Path):
        super().__init__()
        self.violations = violations
        self.output_folder = output_folder
        self.max_retries = max_retries
        self.file_threads = file_threads
        self.project_root = project_root
        self.should_stop = False
        self._mutex = QMutex()

    def stop(self):
        self._mutex.lock()
        self.should_stop = True
        self._mutex.unlock()

    def _is_stopped(self):
        self._mutex.lock()
        v = self.should_stop
        self._mutex.unlock()
        return v

    def run(self):
        try:
            self._run()
        except Exception as exc:
            self.log_signal.emit(f"[ERROR] Unexpected error: {exc}")
            self.log_signal.emit(traceback.format_exc())
            self.finished_signal.emit(False, str(exc))

    def _run(self):
        load_dotenv()

        api_key = os.getenv("key", "").strip()
        api_url = os.getenv("api", "").strip()
        model = os.getenv("model", "gpt-4.1").strip()
        provider = os.getenv("API_PROVIDER", "openai").strip().lower()
        timeout = int(os.getenv("timeout", "120"))

        if provider == "gemini":
            api_url = api_url or "https://generativelanguage.googleapis.com/v1beta/openai/"

        is_claude = (
            any(x in model.lower() for x in ("claude", "sonnet", "haiku", "opus"))
            and (not api_url or "anthropic" in api_url.lower())
        )

        if not api_key:
            self.log_signal.emit("[ERROR] No API key configured. Set 'key' in .env")
            self.finished_signal.emit(False, "No API key")
            return

        from util.translation import getPricingConfig
        pricing = getPricingConfig(model)
        input_cost_per_m  = pricing["inputAPICost"]
        output_cost_per_m = pricing["outputAPICost"]

        terms = load_vocab_terms(self.project_root)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(terms=terms)

        self.log_signal.emit(f"Model: {model}  |  Provider: {'Claude' if is_claude else provider}")
        self.log_signal.emit(
            f"Pricing: ${input_cost_per_m:.4f}/M in  ${output_cost_per_m:.4f}/M out"
        )
        self.log_signal.emit(f"Output folder: {self.output_folder}")
        self.log_signal.emit(
            f"Total violations: {len(self.violations)}  |  Parallel files: {self.file_threads}\n"
        )

        # Shared counters — all accesses protected by _counter_lock
        _counter_lock = threading.Lock()
        _totals = {"done": 0, "failed": 0, "in_tok": 0, "out_tok": 0}
        total = len(self.violations)

        # Group violations by file (preserving order)
        from collections import OrderedDict
        file_groups: dict = OrderedDict()
        for idx, v in enumerate(self.violations):
            file_groups.setdefault(v["file"], []).append((idx, v))

        # ------------------------------------------------------------------ #
        # Per-file worker — runs in a thread-pool thread
        # ------------------------------------------------------------------ #
        def process_file(filename: str, items: list):
            if self._is_stopped():
                return

            self.file_status_signal.emit(filename, "processing")
            file_done = 0
            file_failed = 0

            json_path = self.output_folder / filename
            if not json_path.exists():
                self.log_signal.emit(f"\n[SKIP] {filename} — not found in output folder")
                self.file_status_signal.emit(filename, "skipped")
                with _counter_lock:
                    _totals["failed"] += len(items)
                    self.progress_signal.emit(_totals["done"] + _totals["failed"], total)
                return

            try:
                file_data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception as exc:
                self.log_signal.emit(f"\n[ERROR] Could not read {filename}: {exc}")
                self.file_status_signal.emit(filename, "failed")
                with _counter_lock:
                    _totals["failed"] += len(items)
                    self.progress_signal.emit(_totals["done"] + _totals["failed"], total)
                return

            self.log_signal.emit(
                f"\n{'─'*50}\nFile: {filename}  ({len(items)} violation{'s' if len(items) != 1 else ''})"
            )

            for idx, violation in items:
                if self._is_stopped():
                    break

                original = violation["original"]
                original_flat = original.replace(NEWLINE, "\n")
                entry_index = violation["index"]

                with _counter_lock:
                    pos = _totals["done"] + _totals["failed"] + 1
                self.log_signal.emit(f"\n  [{pos}/{total}] {filename} entry {entry_index}")
                self.log_signal.emit(f"  Original: {repr(original_flat)}")

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": USER_PROMPT_TEMPLATE.format(original_flat=original_flat)},
                ]

                rewrite = None
                for attempt in range(1, self.max_retries + 1):
                    if self._is_stopped():
                        break
                    try:
                        result, in_tok, out_tok = _call_llm(
                            messages, model, api_url, api_key, is_claude, timeout
                        )
                        with _counter_lock:
                            _totals["in_tok"]  += in_tok
                            _totals["out_tok"] += out_tok
                            running_cost = (
                                (_totals["in_tok"]  / 1_000_000) * input_cost_per_m +
                                (_totals["out_tok"] / 1_000_000) * output_cost_per_m
                            )
                        self.cost_signal.emit(running_cost, _totals["in_tok"], _totals["out_tok"])

                        result = _normalise_line_endings(result)
                        result = _sanitise_output(result)
                        issues = is_valid(result)
                        if not issues:
                            rewrite = result
                            self.log_signal.emit(f"  -> OK (attempt {attempt}): {repr(result)}")
                            break
                        else:
                            self.log_signal.emit(f"  -> Attempt {attempt} invalid: {issues}")
                            messages.append({"role": "assistant", "content": result})
                            messages.append({"role": "user", "content": RETRY_PROMPT_TEMPLATE.format(issues="; ".join(issues))})
                    except Exception as exc:
                        self.log_signal.emit(f"  -> Attempt {attempt} API error: {exc}")
                        if attempt < self.max_retries:
                            time.sleep(2)

                if rewrite is not None and not self._is_stopped():
                    entry = file_data[entry_index]
                    if isinstance(entry, dict):
                        entry["message"] = rewrite
                    try:
                        json_path.write_text(
                            json.dumps(file_data, ensure_ascii=False, indent=4) + "\n",
                            encoding="utf-8",
                        )
                    except Exception as exc:
                        self.log_signal.emit(f"  [ERROR] Could not save {filename}: {exc}")
                    file_done += 1
                    with _counter_lock:
                        _totals["done"] += 1
                        self.progress_signal.emit(_totals["done"] + _totals["failed"], total)
                else:
                    file_failed += 1
                    with _counter_lock:
                        _totals["failed"] += 1
                        self.progress_signal.emit(_totals["done"] + _totals["failed"], total)
                    if rewrite is None:
                        self.log_signal.emit(f"  -> FAILED after {self.max_retries} attempts")

            if not self._is_stopped():
                status = "done" if file_failed == 0 else ("partial" if file_done > 0 else "failed")
                self.file_status_signal.emit(filename, status)
                self.log_signal.emit(
                    f"  [FILE DONE] {filename}  ✓ {file_done}  ✗ {file_failed}"
                )

        # ------------------------------------------------------------------ #
        # Dispatch files to thread pool
        # ------------------------------------------------------------------ #
        with ThreadPoolExecutor(max_workers=self.file_threads) as executor:
            futures = {
                executor.submit(process_file, fn, items): fn
                for fn, items in file_groups.items()
            }
            for future in as_completed(futures):
                if self._is_stopped():
                    # Cancel queued (not yet started) futures
                    for f in futures:
                        f.cancel()
                    break
                try:
                    future.result()
                except Exception as exc:
                    fn = futures[future]
                    self.log_signal.emit(f"[ERROR] {fn}: {exc}")

        stopped = self._is_stopped()
        summary = (
            f"Done: {_totals['done']}  Failed: {_totals['failed']}  Total: {total}"
            + ("  (stopped early)" if stopped else "")
        )
        self.log_signal.emit(f"\n{'='*50}\n{summary}")
        self.finished_signal.emit(not stopped and _totals["failed"] == 0, summary)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _make_header(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setStyleSheet("""
        QLabel {
            font-size: 13px;
            font-weight: bold;
            color: #007acc;
            padding: 8px 0px 5px 0px;
            background-color: transparent;
        }
    """)
    return lbl


def _make_hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setStyleSheet("QFrame { color: #555555; margin: 5px 0px; }")
    return line


# ---------------------------------------------------------------------------
# Main tab widget
# ---------------------------------------------------------------------------

class RewriteTab(QWidget):
    """Tab for scanning and fixing over-limit dialogue messages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_root = Path(__file__).resolve().parent.parent
        load_dotenv()
        self._violations: list = []
        self._worker: RewriteWorker | None = None
        # filename → row index in _file_list for fast status updates
        self._file_row: dict = {}
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(4)

        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([380, 800])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root_layout.addWidget(splitter)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(460)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # ---- Folder settings ----
        layout.addWidget(_make_header("Output Folder"))

        folder_row = QHBoxLayout()
        self._folder_edit = QLineEdit()
        self._folder_edit.setPlaceholderText("translated/")
        self._folder_edit.setText(str(self._project_root / "translated"))
        self._folder_edit.setReadOnly(False)
        folder_row.addWidget(self._folder_edit)
        btn_browse_folder = QPushButton("Browse")
        btn_browse_folder.setFixedWidth(72)
        btn_browse_folder.clicked.connect(self._browse_folder)
        folder_row.addWidget(btn_browse_folder)
        layout.addLayout(folder_row)

        layout.addWidget(_make_hline())

        # ---- Violations ----
        layout.addWidget(_make_header("Violations"))

        self._violations_label = QLabel("No violations loaded.")
        self._violations_label.setWordWrap(True)
        self._violations_label.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        layout.addWidget(self._violations_label)

        self._estimate_label = QLabel("")
        self._estimate_label.setWordWrap(True)
        self._estimate_label.setStyleSheet("color: #9cdcfe; font-size: 11px;")
        layout.addWidget(self._estimate_label)

        scan_row = QHBoxLayout()
        self._btn_scan = QPushButton("Scan Folder")
        self._btn_scan.setToolTip("Scan the output folder and load violations")
        self._btn_scan.clicked.connect(self._scan_folder)
        scan_row.addWidget(self._btn_scan)

        self._btn_load_violations = QPushButton("Load JSON")
        self._btn_load_violations.setToolTip("Load an existing violations.json file")
        self._btn_load_violations.clicked.connect(self._load_violations_file)
        scan_row.addWidget(self._btn_load_violations)
        layout.addLayout(scan_row)

        layout.addWidget(_make_hline())

        # ---- Rewrite settings ----
        layout.addWidget(_make_header("Settings"))

        retry_row = QHBoxLayout()
        retry_row.addWidget(QLabel("Max retries per message:"))
        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(1, 10)
        self._retry_spin.setValue(3)
        self._retry_spin.setFixedWidth(60)
        retry_row.addWidget(self._retry_spin)
        retry_row.addStretch()
        layout.addLayout(retry_row)

        threads_row = QHBoxLayout()
        threads_row.addWidget(QLabel("Parallel files:"))
        self._threads_spin = QSpinBox()
        self._threads_spin.setRange(1, 20)
        default_threads = int(os.getenv("fileThreads", "1"))
        self._threads_spin.setValue(max(1, default_threads))
        self._threads_spin.setFixedWidth(60)
        self._threads_spin.setToolTip(
            "Number of files to process simultaneously.\n"
            "Defaults to fileThreads from .env. Keep low for free-tier APIs."
        )
        threads_row.addWidget(self._threads_spin)
        threads_row.addStretch()
        layout.addLayout(threads_row)

        layout.addWidget(_make_hline())

        # ---- Progress ----
        layout.addWidget(_make_header("Progress"))

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        self._progress_label = QLabel("Idle")
        self._progress_label.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        layout.addWidget(self._progress_label)

        self._cost_label = QLabel("Cost: $0.0000")
        self._cost_label.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        layout.addWidget(self._cost_label)

        layout.addWidget(_make_hline())

        # ---- Action buttons ----
        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("Start Rewrite")
        self._btn_start.setEnabled(False)
        self._btn_start.setStyleSheet("""
            QPushButton { background-color: #2ea043; }
            QPushButton:hover { background-color: #3fb950; }
            QPushButton:disabled { background-color: #404040; color: #888888; }
        """)
        self._btn_start.clicked.connect(self._start_rewrite)
        btn_row.addWidget(self._btn_start)

        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setEnabled(False)
        self._btn_stop.setStyleSheet("""
            QPushButton { background-color: #da3633; }
            QPushButton:hover { background-color: #f85149; }
            QPushButton:disabled { background-color: #404040; color: #888888; }
        """)
        self._btn_stop.clicked.connect(self._stop_rewrite)
        btn_row.addWidget(self._btn_stop)
        layout.addLayout(btn_row)

        layout.addStretch()
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 10, 10, 10)
        layout.setSpacing(6)

        splitter = QSplitter(Qt.Vertical)
        splitter.setHandleWidth(4)

        # File checklist
        file_container = QWidget()
        file_layout = QVBoxLayout(file_container)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(4)

        file_header_row = QHBoxLayout()
        file_header_row.addWidget(_make_header("Files"))
        file_header_row.addStretch()
        btn_all = QPushButton("All")
        btn_all.setToolTip("Select all files")
        btn_all.clicked.connect(lambda: self._set_all_checked(True))
        btn_none = QPushButton("None")
        btn_none.setToolTip("Deselect all files")
        btn_none.clicked.connect(lambda: self._set_all_checked(False))
        file_header_row.addWidget(btn_all)
        file_header_row.addWidget(btn_none)
        file_layout.addLayout(file_header_row)

        self._file_list = QListWidget()
        self._file_list.setFont(QFont("Consolas", 9))
        file_layout.addWidget(self._file_list)
        splitter.addWidget(file_container)

        # Log area
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(_make_header("Log"))
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self._log_text)
        splitter.addWidget(log_container)

        splitter.setSizes([300, 400])
        layout.addWidget(splitter)
        return panel

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self._folder_edit.text()
        )
        if folder:
            self._folder_edit.setText(folder)

    def _scan_folder(self):
        folder = Path(self._folder_edit.text().strip())
        if not folder.exists():
            QMessageBox.warning(self, "Folder Not Found", f"Folder does not exist:\n{folder}")
            return

        self._log("Scanning folder for violations...")
        violations = scan_folder(folder)

        # Save violations.json next to the project root
        out_path = self._project_root / "violations.json"
        try:
            out_path.write_text(
                json.dumps(violations, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._log(f"Saved {len(violations)} violations → {out_path}")
        except Exception as exc:
            self._log(f"[WARNING] Could not save violations.json: {exc}")

        self._load_violations(violations)

    def _load_violations_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Violations File",
            str(self._project_root),
            "JSON Files (*.json);;All Files (*)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("Expected a JSON array")
            self._load_violations(data)
            self._log(f"Loaded {len(data)} violations from {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Failed to load violations:\n{exc}")

    def _load_violations(self, violations: list):
        self._violations = violations
        self._file_list.clear()
        self._file_row.clear()

        # Group by file, preserving order
        from collections import defaultdict, OrderedDict
        file_groups: dict = OrderedDict()
        for v in violations:
            file_groups.setdefault(v["file"], []).append(v)

        for row, (filename, items) in enumerate(file_groups.items()):
            n = len(items)
            label = f"{filename}  ({n} violation{'s' if n != 1 else ''})"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setForeground(QColor("#cccccc"))
            item.setData(Qt.UserRole, filename)
            self._file_list.addItem(item)
            self._file_row[filename] = row

        n_files = len(file_groups)
        count = len(violations)
        self._violations_label.setText(
            f"{count} violation{'s' if count != 1 else ''} across {n_files} file{'s' if n_files != 1 else ''}."
        )
        self._estimate_label.setText("Estimating cost...")
        self._btn_start.setEnabled(count > 0)

        if count > 0:
            self._log(f"Loaded {count} violations across {n_files} files.")
            self._run_cost_estimate(violations)
        else:
            self._log("No violations found.")
            self._estimate_label.setText("")

    def _set_all_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for i in range(self._file_list.count()):
            self._file_list.item(i).setCheckState(state)

    def _checked_violations(self) -> list:
        """Return only violations belonging to checked files."""
        checked_files = set()
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item.checkState() == Qt.Checked:
                checked_files.add(item.data(Qt.UserRole))
        return [v for v in self._violations if v["file"] in checked_files]

    def _run_cost_estimate(self, violations: list):
        """Compute cost estimate in a background thread and update the label."""
        project_root = self._project_root

        class _EstimateThread(QThread):
            done = pyqtSignal(str)
            def run(self_t):
                self_t.done.emit(estimate_run_cost(violations, project_root))

        self._estimate_thread = _EstimateThread(self)
        self._estimate_thread.done.connect(
            lambda text: self._estimate_label.setText(f"Est. cost: {text}")
        )
        self._estimate_thread.done.connect(
            lambda text: self._log(f"Cost estimate: {text}")
        )
        self._estimate_thread.start()

    def _start_rewrite(self):
        if not self._violations:
            QMessageBox.information(self, "No Violations", "Scan or load violations first.")
            return

        violations = self._checked_violations()
        if not violations:
            QMessageBox.information(self, "No Files Selected",
                                    "Check at least one file in the file list.")
            return

        folder = Path(self._folder_edit.text().strip())
        if not folder.exists():
            QMessageBox.warning(self, "Folder Not Found", f"Output folder not found:\n{folder}")
            return

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_scan.setEnabled(False)
        self._btn_load_violations.setEnabled(False)
        self._progress_bar.setValue(0)
        self._progress_label.setText("Starting...")
        self._cost_label.setText("Cost: $0.0000")
        self._log("\n" + "="*50)
        n_files = len({v["file"] for v in violations})
        self._log(f"Starting rewrite: {len(violations)} violations across {n_files} files...")

        # Reset file list colours for checked items only
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item.checkState() == Qt.Checked:
                item.setForeground(QColor("#cccccc"))

        self._worker = RewriteWorker(
            violations=violations,
            output_folder=folder,
            max_retries=self._retry_spin.value(),
            file_threads=self._threads_spin.value(),
            project_root=self._project_root,
        )
        self._worker.log_signal.connect(self._log)
        self._worker.file_status_signal.connect(self._on_file_status)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.cost_signal.connect(self._on_cost)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.start()

    def _stop_rewrite(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._btn_stop.setEnabled(False)
            self._progress_label.setText("Stopping...")
            self._log("Stop requested...")

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _on_file_status(self, filename: str, status: str):
        row = self._file_row.get(filename)
        if row is None:
            return
        item = self._file_list.item(row)
        if item is None:
            return
        colors = {
            "processing": "#007acc",
            "done":       "#2ea043",
            "partial":    "#e3b341",   # some succeeded, some failed
            "failed":     "#da3633",
            "skipped":    "#888888",
        }
        item.setForeground(QColor(colors.get(status, "#cccccc")))

    def _on_progress(self, current: int, total: int):
        if total > 0:
            pct = int(current / total * 100)
            self._progress_bar.setValue(pct)
            self._progress_label.setText(f"{current} / {total} ({pct}%)")

    def _on_cost(self, cost: float, in_tok: int, out_tok: int):
        self._cost_label.setText(
            f"Cost: ${cost:.4f}  ({in_tok:,} in / {out_tok:,} out tokens)"
        )

    def _on_finished(self, success: bool, message: str):
        self._btn_start.setEnabled(bool(self._violations))
        self._btn_stop.setEnabled(False)
        self._btn_scan.setEnabled(True)
        self._btn_load_violations.setEnabled(True)
        self._progress_label.setText("Finished")
        self._worker = None

    # ------------------------------------------------------------------
    # Log helper
    # ------------------------------------------------------------------

    def _log(self, text: str):
        self._log_text.append(text)
        # Auto-scroll
        sb = self._log_text.verticalScrollBar()
        sb.setValue(sb.maximum())
