#!/usr/bin/env python3
"""
DazedTL GUI - Main Application
A PyQt-based graphical user interface for the DazedTL translation system.
"""

import re
import sys
import os
import json
import urllib.request
import zipfile
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

if sys.platform.startswith("linux"):
    from util.linux_desktop import configure_qt_platform

    configure_qt_platform()

# Must run before PyQt5 loads - see the note in scripts/start_gui.py. Repeated
# here because this module is also imported directly, and prepare() is a no-op
# on the second call.
from util.msvc_runtime import prepare as _prepare_msvc_runtime  # noqa: E402

_prepare_msvc_runtime()

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QLabel, QFileDialog, QMessageBox, QProgressBar,
    QTextEdit, QSplitter, QGroupBox, QStatusBar, QStackedWidget, QToolButton,
    QDialog, QComboBox, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSettings, QCoreApplication
from PyQt5.QtGui import QIcon, QFont, QPixmap, QScreen, QGuiApplication


from util.paths import (
    APP_NAME,
    ICON_PATH,
    LAST_UPDATE_SHA_PATH,
    ORG_NAME,
    PROJECT_ROOT,
    migrate_app_settings,
)


def load_application_icon() -> QIcon:
    """Prefer ICO on Windows; PNG is fine for all platforms. Empty if missing."""
    for path in (PROJECT_ROOT / "assets/icon.ico", ICON_PATH):
        if path.is_file():
            icon = QIcon(str(path))
            if not icon.isNull():
                return icon
    return QIcon()


def configured_font_scale() -> float:
    """Return the persisted UI scale, clamped to the Configuration range."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
        return max(0.5, min(3.0, float(os.getenv("font_scale", "1.0"))))
    except (TypeError, ValueError):
        return 1.0


def check_tool_update() -> str | None:
    """Return latest commit SHA when a tool update is available, else None."""
    latest_sha = UpdateThread.fetch_latest_sha()
    current_sha = UpdateThread.read_installed_sha()
    if latest_sha != current_sha:
        return latest_sha
    return None


class BackgroundUpdateCheckThread(QThread):
    """Checks for DazedTL updates without blocking the UI."""

    checked = pyqtSignal(object, str)  # candidate-or-None, error

    def run(self):
        try:
            self.checked.emit(check_tool_update(), "")
        except Exception as exc:
            self.checked.emit(None, str(exc))


@dataclass(frozen=True)
class UpdateSource:
    """One public mirror capable of resolving and downloading a tool build."""

    name: str
    branch_url: str
    archive_url: str
    sha_path: tuple[str, ...]


class UpdateCandidate(str):
    """A commit SHA paired with the mirror that resolved it."""

    source: UpdateSource

    def __new__(cls, sha: str, source: UpdateSource):
        value = str.__new__(cls, sha)
        value.source = source
        return value


class UpdateThread(QThread):
    """Downloads and applies a tool update from the first healthy mirror."""

    REPO_HOST = "https://git.dazedtl.dev"
    REPO_OWNER = "dazed"
    REPO_SLUG = "dazed-mtl-tool"
    REPO_BRANCH = "main"
    UPDATE_SOURCES = (
        UpdateSource(
            "GitHub",
            "https://api.github.com/repos/dazedanon/DazedMTLTool/branches/{branch}",
            "https://github.com/dazedanon/DazedMTLTool/archive/{sha}.zip",
            ("commit", "sha"),
        ),
        UpdateSource(
            "GitGud",
            "https://gitgud.io/api/v4/projects/DazedAnon%2FDazedMTLTool/repository/branches/{branch}",
            "https://gitgud.io/DazedAnon/DazedMTLTool/-/archive/{sha}/DazedMTLTool-{sha}.zip",
            ("commit", "id"),
        ),
        UpdateSource(
            "git.dazedtl.dev",
            "https://git.dazedtl.dev/api/v1/repos/dazed/DazedTL/branches/{branch}",
            "https://git.dazedtl.dev/dazed/DazedTL/archive/{sha}.zip",
            ("commit", "id"),
        ),
    )
    # Gitea names the archive top folder after the repo display name (currently
    # "dazedtl"). Resolve dynamically so a rename cannot silently no-op again.
    ARCHIVE_ROOT = "dazedtl"
    SHA_FILE = str(LAST_UPDATE_SHA_PATH)
    ARCHIVE_SHA_FILE = str(PROJECT_ROOT / ".git_archival.txt")

    # Top-level paths that should never be touched during update
    PROTECTED_TOP = {
        ".agents",
        ".codex",
        ".cursor",
        ".env",
        ".github",
        ".vscode",
        "venv",
        "log",
        "files",
        "translated",
    }

    # User-local files under data/ that must not be overwritten.
    # Shipped defaults (translation_contexts.json, skills/*.md, help/*, glossary_base.txt, …)
    # are intentionally updated so tool releases refresh prompts, Guide docs, and contexts.
    PROTECTED_DATA_FILES = frozenset({
        "data/vocab.txt",
        "data/last_update_sha.txt",
        "data/wolf_speakers.json",
        "data/wolf_safe_notes.json",
        "data/api_keys.json",
    })

    # GitLab zip archives do not preserve Unix execute bits; restore after apply.
    EXECUTABLE_SUFFIXES = {".sh", ".desktop"}

    progress  = pyqtSignal(str, int, str)  # (stage, percent or -1, detail)
    finished  = pyqtSignal(bool, str)       # (success, message)

    STAGES = ("Downloading", "Extracting", "Applying")

    def __init__(self, parent=None, candidate: UpdateCandidate | None = None):
        super().__init__(parent)
        self._candidate = candidate

    @classmethod
    def should_install(cls, rel: Path) -> bool:
        """Return True when *rel* (path relative to archive root) may be copied."""
        parts = rel.parts
        if not parts:
            return False
        if parts[0] in cls.PROTECTED_TOP:
            return False
        if rel.as_posix() in cls.PROTECTED_DATA_FILES:
            return False
        return True

    @classmethod
    def should_install_to_root(cls, rel: Path, root: Path) -> bool:
        """Return True when *rel* may be copied into the selected install root.

        Git expands ``.git_archival.txt`` while creating a source archive. Keep
        that expanded file in archive-only installs, but do not copy it back
        into a live checkout where it would dirty the worktree on every update.
        """
        if not cls.should_install(rel):
            return False
        if rel.as_posix() == ".git_archival.txt" and (root / ".git").exists():
            return False
        return True

    @classmethod
    def resolve_archive_root(cls, extract_dir: Path) -> Path:
        """Locate the single top-level folder inside an extracted archive.

        Prefers ``ARCHIVE_ROOT`` when present; otherwise accepts exactly one
        subdirectory (Gitea zip layout). Raises if the layout is unexpected.
        """
        preferred = extract_dir / cls.ARCHIVE_ROOT
        if preferred.is_dir():
            return preferred
        dirs = sorted(p for p in extract_dir.iterdir() if p.is_dir())
        if len(dirs) == 1:
            return dirs[0]
        found = [p.name for p in dirs]
        raise FileNotFoundError(
            f"Could not find update archive root under {extract_dir} "
            f"(expected {cls.ARCHIVE_ROOT!r}; found {found})"
        )

    @staticmethod
    def _fmt_bytes(num: int) -> str:
        if num >= 1024 * 1024:
            return f"{num / (1024 * 1024):.1f} MB"
        if num >= 1024:
            return f"{num / 1024:.0f} KB"
        return f"{num} B"

    # ------------------------------------------------------------------ #

    def run(self):
        try:
            latest_sha = self._candidate or self._fetch_latest_sha()
            current_sha = self._read_stored_sha()

            if latest_sha == current_sha:
                self.finished.emit(True, "already_up_to_date")
                return

            self._download_and_apply(latest_sha)

        except Exception as exc:
            self.finished.emit(False, str(exc))

    @classmethod
    def branch_api_url(cls, source: UpdateSource | None = None) -> str:
        source = source or cls.UPDATE_SOURCES[0]
        return source.branch_url.format(branch=cls.REPO_BRANCH)

    @classmethod
    def archive_zip_url(
        cls,
        source: UpdateSource | None = None,
        sha: str | None = None,
    ) -> str:
        source = source or cls.UPDATE_SOURCES[0]
        return source.archive_url.format(
            branch=cls.REPO_BRANCH,
            sha=sha or cls.REPO_BRANCH,
        )

    @classmethod
    def _fetch_source_sha(cls, source: UpdateSource) -> str:
        req = urllib.request.Request(
            cls.branch_api_url(source), headers={"User-Agent": APP_NAME}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
        value = payload
        for key in source.sha_path:
            value = value[key]
        sha = str(value).strip()
        if re.fullmatch(r"[0-9a-fA-F]{40,64}", sha) is None:
            raise ValueError(f"{source.name} returned an invalid commit SHA")
        return sha.lower()

    @classmethod
    def fetch_latest_sha(cls) -> UpdateCandidate:
        errors = []
        for source in cls.UPDATE_SOURCES:
            try:
                return UpdateCandidate(cls._fetch_source_sha(source), source)
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
        raise RuntimeError(
            "Could not reach any update source. " + " | ".join(errors)
        )

    @staticmethod
    def _read_archive_sha(path: Path) -> str:
        """Read an expanded git-archive commit ID, or return an empty string."""
        if not path.is_file():
            return ""
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition(":")
                candidate = value.strip()
                if (
                    separator
                    and key.strip() == "node"
                    and re.fullmatch(r"[0-9a-fA-F]{40,64}", candidate)
                ):
                    return candidate
        except OSError:
            pass
        return ""

    @staticmethod
    def _read_git_sha(root: Path) -> str:
        """Read HEAD from a live checkout, or return an empty string."""
        # Do not let Git discover an unrelated repository above an extracted
        # DazedTL folder. Worktrees use a .git file, so ``exists`` covers both.
        if not (root / ".git").exists():
            return ""
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        candidate = result.stdout.strip()
        if result.returncode == 0 and re.fullmatch(
            r"[0-9a-fA-F]{40,64}", candidate
        ):
            return candidate.lower()
        return ""

    @classmethod
    def read_installed_sha(cls) -> str:
        """Return the installed SHA from runtime, archive, or Git metadata."""
        runtime_path = Path(cls.SHA_FILE)
        if runtime_path.is_file():
            try:
                runtime_sha = runtime_path.read_text(encoding="utf-8").strip()
                if runtime_sha:
                    return runtime_sha
            except OSError:
                pass
        archive_path = Path(cls.ARCHIVE_SHA_FILE)
        archive_sha = cls._read_archive_sha(archive_path)
        if archive_sha:
            return archive_sha
        return cls._read_git_sha(archive_path.parent)

    # ------------------------------------------------------------------ #

    def _fetch_latest_sha(self):
        return self.fetch_latest_sha()

    def _read_stored_sha(self):
        return self.read_installed_sha()

    def _download_archive(self, zip_path: Path, candidate: UpdateCandidate):
        start_index = self.UPDATE_SOURCES.index(candidate.source)
        errors = []
        for index, source in enumerate(self.UPDATE_SOURCES[start_index:]):
            try:
                if index and self._fetch_source_sha(source) != str(candidate):
                    raise RuntimeError(
                        "mirror has not synchronized the selected commit"
                    )
                req = urllib.request.Request(
                    self.archive_zip_url(source, str(candidate)),
                    headers={"User-Agent": APP_NAME},
                )
                with urllib.request.urlopen(req, timeout=120) as resp, open(
                    zip_path, "wb"
                ) as fh:
                    total = int(resp.headers.get("Content-Length", 0) or 0)
                    downloaded = 0
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(70, int(downloaded * 70 / total))
                            detail = (
                                f"{source.name}: {self._fmt_bytes(downloaded)} "
                                f"of {self._fmt_bytes(total)}"
                            )
                        else:
                            pct = -1
                            detail = (
                                f"{source.name}: "
                                f"{self._fmt_bytes(downloaded)} downloaded"
                            )
                        self.progress.emit("Downloading", pct, detail)
                return
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
        raise RuntimeError(
            "Could not download the selected update. " + " | ".join(errors)
        )

    def _download_and_apply(self, latest_sha):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            zip_path = tmp / "update.zip"

            self.progress.emit(
                "Downloading",
                -1,
                f"Fetching archive from {latest_sha.source.name}",
            )
            self._download_archive(zip_path, latest_sha)

            self.progress.emit("Extracting", 75, "Unpacking update archive…")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp)

            extracted = self.resolve_archive_root(tmp)
            root = PROJECT_ROOT.resolve()

            install_files = [
                src
                for src in extracted.rglob("*")
                if src.is_file()
                and self.should_install_to_root(
                    src.relative_to(extracted),
                    root,
                )
            ]
            if not install_files:
                raise RuntimeError(
                    "Update archive contained no installable files "
                    f"(root={extracted.name!r})"
                )

            total_files = len(install_files)
            self.progress.emit("Applying", 85, "Installing updated files…")
            for index, src in enumerate(install_files, start=1):
                rel = src.relative_to(extracted)
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                if dst.suffix in self.EXECUTABLE_SUFFIXES:
                    mode = dst.stat().st_mode | 0o111
                    dst.chmod(mode)
                pct = 85 + int(index * 15 / total_files)
                self.progress.emit("Applying", min(100, pct), str(rel))

        Path(self.SHA_FILE).write_text(latest_sha)
        self.finished.emit(True, f"updated:{latest_sha[:8]}")


class UpdateDialog(QDialog):
    """Modal dialog that shows update progress and result."""

    _DIALOG_STYLE = """
        QDialog {
            background-color: #2b2b2b;
        }
        QLabel#updateTitle {
            font-size: 18px;
            font-weight: bold;
            color: #ffffff;
            background: transparent;
        }
        QLabel#updateHeadline {
            font-size: 14px;
            font-weight: bold;
            color: #ffffff;
            background: transparent;
        }
        QLabel#updateDetail {
            font-size: 12px;
            color: #aaaaaa;
            background: transparent;
        }
        QLabel#updateVersionKey {
            font-size: 11px;
            color: #888888;
            background: transparent;
        }
        QLabel#updateVersionValue {
            font-size: 13px;
            font-weight: bold;
            color: #ffffff;
            background: transparent;
            font-family: Consolas, "Courier New", monospace;
        }
        QLabel#updateVersionArrow {
            font-size: 16px;
            color: #007acc;
            background: transparent;
            padding: 0 8px;
        }
        QFrame#updateVersionFrame {
            background-color: #353535;
            border: 1px solid #4a4a4a;
            border-radius: 6px;
        }
        QLabel#updateStep {
            font-size: 11px;
            color: #777777;
            background-color: #3a3a3a;
            border: 1px solid #4a4a4a;
            border-radius: 10px;
            padding: 4px 10px;
        }
        QLabel#updateStepActive {
            font-size: 11px;
            color: #ffffff;
            background-color: #007acc;
            border: 1px solid #007acc;
            border-radius: 10px;
            padding: 4px 10px;
        }
        QLabel#updateStepDone {
            font-size: 11px;
            color: #ffffff;
            background-color: #2d6a4f;
            border: 1px solid #40916c;
            border-radius: 10px;
            padding: 4px 10px;
        }
        QPushButton#updatePrimaryBtn {
            background-color: #0078d4;
            color: #ffffff;
            border: none;
            padding: 8px 18px;
            border-radius: 4px;
            font-weight: bold;
            min-width: 110px;
        }
        QPushButton#updatePrimaryBtn:hover {
            background-color: #106ebe;
        }
        QPushButton#updateSecondaryBtn {
            background-color: #404040;
            color: #ffffff;
            border: 1px solid #555555;
            padding: 8px 18px;
            border-radius: 4px;
            min-width: 90px;
        }
        QPushButton#updateSecondaryBtn:hover {
            background-color: #4a4a4a;
        }
        QProgressBar {
            background-color: #404040;
            border: 1px solid #555555;
            border-radius: 4px;
            text-align: center;
            color: #ffffff;
            height: 22px;
        }
        QProgressBar::chunk {
            background-color: #007acc;
            border-radius: 3px;
        }
    """

    def __init__(self, parent=None, pending_tool_sha: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Tool Update")
        self.setMinimumWidth(480)
        self.setModal(True)
        self.setObjectName("appUpdateDialog")

        self._thread = None
        self._pending_tool_sha = pending_tool_sha
        self._check_error = ""
        self._current_stage = ""
        self._step_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel()
        app_icon = load_application_icon()
        if not app_icon.isNull():
            icon.setPixmap(app_icon.pixmap(40, 40))
        else:
            icon.setText("⬆")
            icon.setStyleSheet("font-size: 28px; background: transparent;")
        header.addWidget(icon)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        self.title_label = QLabel(f"{APP_NAME} Update")
        self.title_label.setObjectName("appPageTitle")
        self.subtitle_label = QLabel("Stay current with the latest fixes and features.")
        self.subtitle_label.setObjectName("updateDetail")
        title_col.addWidget(self.title_label)
        title_col.addWidget(self.subtitle_label)
        header.addLayout(title_col, stretch=1)
        layout.addLayout(header)

        self.version_frame = QFrame()
        self.version_frame.setObjectName("updateVersionFrame")
        version_layout = QHBoxLayout(self.version_frame)
        version_layout.setContentsMargins(16, 12, 16, 12)
        version_layout.setSpacing(0)

        current_col = QVBoxLayout()
        current_col.setSpacing(4)
        current_key = QLabel("Installed")
        current_key.setObjectName("updateVersionKey")
        self.current_version_label = QLabel(self._installed_sha_display())
        self.current_version_label.setObjectName("updateVersionValue")
        current_col.addWidget(current_key)
        current_col.addWidget(self.current_version_label)

        arrow = QLabel("→")
        arrow.setObjectName("updateVersionArrow")
        arrow.setAlignment(Qt.AlignCenter)

        new_col = QVBoxLayout()
        new_col.setSpacing(4)
        new_key = QLabel("Available")
        new_key.setObjectName("updateVersionKey")
        self.new_version_label = QLabel("Checking…")
        self.new_version_label.setObjectName("updateVersionValue")
        new_col.addWidget(new_key)
        new_col.addWidget(self.new_version_label)

        version_layout.addLayout(current_col, stretch=1)
        version_layout.addWidget(arrow)
        version_layout.addLayout(new_col, stretch=1)
        layout.addWidget(self.version_frame)

        self.headline_label = QLabel("Checking for updates…")
        self.headline_label.setObjectName("updateHeadline")
        self.headline_label.setWordWrap(True)
        layout.addWidget(self.headline_label)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("updateDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        steps_row = QHBoxLayout()
        steps_row.setSpacing(8)
        for stage in UpdateThread.STAGES:
            pill = QLabel(stage)
            pill.setObjectName("updateStep")
            pill.setAlignment(Qt.AlignCenter)
            self._step_labels[stage] = pill
            steps_row.addWidget(pill)
        steps_row.addStretch()
        self.steps_widget = QWidget()
        self.steps_widget.setLayout(steps_row)
        layout.addWidget(self.steps_widget)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        from gui.ui_components import configure_action_button
        configure_action_button(self.cancel_btn, variant="quiet")
        self.cancel_btn.clicked.connect(self.reject)
        self.action_btn = QPushButton("Install update")
        configure_action_button(self.action_btn, variant="primary")
        self.action_btn.clicked.connect(self._on_action)
        self.action_btn.hide()
        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.action_btn)
        layout.addLayout(button_row)

    @staticmethod
    def _short_sha(sha: str | None) -> str:
        if not sha:
            return "Unknown"
        return sha[:8]

    @classmethod
    def _installed_sha_display(cls) -> str:
        return cls._short_sha(UpdateThread.read_installed_sha())

    def _set_stage_pills(self, active_stage: str | None = None):
        stage_order = list(UpdateThread.STAGES)
        active_index = stage_order.index(active_stage) if active_stage in stage_order else -1
        for index, stage in enumerate(stage_order):
            pill = self._step_labels[stage]
            if active_stage and index < active_index:
                pill.setObjectName("updateStepDone")
            elif stage == active_stage:
                pill.setObjectName("updateStepActive")
            else:
                pill.setObjectName("updateStep")
            pill.style().unpolish(pill)
            pill.style().polish(pill)

    def _set_progress(self, percent: int):
        if percent < 0:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("")
            return
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(max(0, min(100, percent)))
        self.progress_bar.setFormat("%p%")

    def _show_checking(self):
        self._check_error = ""
        self.headline_label.setText("Checking for updates…")
        self.detail_label.setText(
            f"Checking update mirrors ({UpdateThread.REPO_BRANCH})"
        )
        self.new_version_label.setText("Checking…")
        self.action_btn.setText("Install update")
        self.action_btn.hide()
        self.cancel_btn.setText("Cancel")
        self.steps_widget.hide()
        self._set_progress(-1)

    def start(self):
        self._show_checking()
        if self._pending_tool_sha:
            self._show_pending_updates()
            return

        self._thread = BackgroundUpdateCheckThread(parent=self)
        self._thread.checked.connect(self._on_check_finished)
        self._thread.start()

    def _show_pending_updates(self):
        self.steps_widget.hide()
        self._set_progress(-1)
        self.progress_bar.hide()
        self.cancel_btn.setText("Close")

        tool_sha = self._pending_tool_sha
        self.new_version_label.setText(self._short_sha(tool_sha))

        if not tool_sha:
            self.headline_label.setText("You're up to date")
            self.detail_label.setText(
                f"No newer build found on {UpdateThread.REPO_BRANCH}."
            )
            self.subtitle_label.setText("You're running the latest version.")
            self.action_btn.hide()
            return

        self.headline_label.setText("A new version is available")
        self.detail_label.setText(
            "Install the update to get the latest improvements. "
            "Your config, projects, and translated files are preserved."
        )
        self.subtitle_label.setText("A newer build is ready to install.")
        self.action_btn.show()
        self.cancel_btn.setText("Not now")

    def _show_check_failed(self, error: str):
        self._check_error = error
        self._pending_tool_sha = None
        self.steps_widget.hide()
        self.progress_bar.hide()
        self.new_version_label.setText("Unavailable")
        self.headline_label.setText("Could not check for updates")
        self.detail_label.setText(error)
        self.subtitle_label.setText(
            "No update source could be reached; your installed version was not verified."
        )
        self.action_btn.setText("Retry")
        self.action_btn.show()
        self.cancel_btn.setText("Close")

    def _on_check_finished(self, tool_sha: str | None, error: str):
        if error:
            self._show_check_failed(error)
            return
        self._pending_tool_sha = tool_sha
        self._show_pending_updates()

    def _on_action(self):
        if self._check_error:
            self.start()
            return
        self._do_update()

    def _on_progress(self, stage: str, percent: int, detail: str):
        self._current_stage = stage
        self.steps_widget.show()
        self.progress_bar.show()
        self._set_stage_pills(stage)
        self.headline_label.setText(stage)
        self.detail_label.setText(detail)
        self._set_progress(percent)

    def _on_finished(self, success, message):
        self.steps_widget.hide()
        self.action_btn.hide()
        self.cancel_btn.setText("Close")

        if not success:
            self.progress_bar.hide()
            self.headline_label.setText("Update failed")
            self.detail_label.setText(message)
            self.subtitle_label.setText("Something went wrong while updating.")
            return

        self.progress_bar.show()
        self._set_progress(100)

        if message == "already_up_to_date":
            self.headline_label.setText("You're up to date")
            self.detail_label.setText(
                f"No newer build found on {UpdateThread.REPO_BRANCH}."
            )
            self.subtitle_label.setText("You're running the latest version.")
            self.new_version_label.setText(self._installed_sha_display())
        elif message.startswith("updated:"):
            sha = message.split(":", 1)[1]
            self._pending_tool_sha = None
            self.new_version_label.setText(sha)
            self.current_version_label.setText(sha)
            self.headline_label.setText("Update installed successfully")
            self.detail_label.setText(
                f"Restart {APP_NAME} to load the new version."
            )
            self.subtitle_label.setText("Update complete.")
            if isinstance(self.parent(), DazedMTLGUI):
                self.parent().clear_update_indicator()

    def _do_update(self):
        self.progress_bar.show()
        self.action_btn.hide()
        self.cancel_btn.setText("Cancel")
        self.subtitle_label.setText("Installing the latest build…")
        self.steps_widget.show()
        self._set_stage_pills("Downloading")
        self._set_progress(-1)

        if self._pending_tool_sha:
            self.new_version_label.setText(self._short_sha(self._pending_tool_sha))
            self.headline_label.setText("Downloading")
            self.detail_label.setText(
                f"Fetching verified build {self._short_sha(self._pending_tool_sha)}"
            )
            candidate = (
                self._pending_tool_sha
                if isinstance(self._pending_tool_sha, UpdateCandidate)
                else None
            )
            self._thread = UpdateThread(parent=self, candidate=candidate)
            self._thread.progress.connect(self._on_progress)
            self._thread.finished.connect(self._on_finished)
            self._thread.start()
            return

        self._set_progress(100)
        self.headline_label.setText("You're up to date")
        self.detail_label.setText(
            f"No newer build found on {UpdateThread.REPO_BRANCH}."
        )

# Import configuration widgets
from gui.config_tab import ConfigTab
from gui.guide_tab import GuideTab
from gui.translation_tab import TranslationTab
from gui.image_manager import ImageManager
from gui.version_update_tab import VersionUpdateTab
from gui.skills_tab import SkillsTab
from gui.batch_tab import BatchTab
from gui.evaluation_tab import EvaluationTab

class DazedMTLGUI(QMainWindow):
    """Main GUI window for DazedTL."""

    PAGE_GUIDE = 0
    PAGE_WORKFLOW = 1
    PAGE_IMAGES = 2
    PAGE_VERSION_UPDATE = 3
    PAGE_TRANSLATION = 4
    PAGE_BATCHES = 5
    PAGE_SKILLS = 6
    PAGE_CONFIG = 7
    PAGE_EVALUATION = 8

    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self._pending_tool_sha: str | None = None
        self._update_check_error = ""
        self._update_check_thread = None
        self._shutdown_started = False
        self._applied_font_scale: float | None = None
        self._update_icon = "🔄"
        self.btn_update = None
        self.init_ui()
        self.setup_status_bar()
        self.setup_font_scaling()
        self.restore_window_state()
        QTimer.singleShot(500, self.start_background_update_check)
        
    def restore_window_state(self):
        """Restore window geometry and state from settings."""
        try:
            # Restore window geometry
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
            
            # Restore window state (maximized, etc.)
            window_state = self.settings.value("windowState")
            if window_state:
                self.restoreState(window_state)
                
        except Exception as e:
            print(f"Warning: Could not restore window state: {e}")
            
    def save_window_state(self):
        """Save window geometry and state to settings."""
        try:
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("windowState", self.saveState())
        except Exception as e:
            print(f"Warning: Could not save window state: {e}")
            
    def stop_all_background_threads(self):
        """Gracefully stop every background ``QThread`` before the process exits.

        A ``QThread`` that is destroyed while still running aborts the whole
        process with SIGABRT. Idempotent so ``closeEvent`` and ``aboutToQuit``
        can both call this safely.
        """
        if getattr(self, "_shutdown_started", False):
            return
        self._shutdown_started = True

        import gc

        current = QThread.currentThread()
        for obj in gc.get_objects():
            try:
                if not isinstance(obj, QThread) or obj is current:
                    continue
                if not obj.isRunning():
                    continue
                for stopper in ("stop", "requestInterruption"):
                    fn = getattr(obj, stopper, None)
                    if callable(fn):
                        try:
                            fn()
                        except Exception:
                            pass
                if not obj.wait(400):
                    if getattr(obj, "_graceful_shutdown_only", False):
                        # Python model workers cannot be safely terminated.
                        # Their shared stop event lets them finish the current
                        # provider call, checkpoint, and unwind the executor.
                        obj.wait()
                        continue
                    try:
                        obj.terminate()
                        obj.wait(400)
                    except Exception:
                        pass
            except Exception:
                continue

    def closeEvent(self, event):
        """Handle application close event."""
        try:
            self.save_window_state()
        except Exception:
            pass

        try:
            if hasattr(self, 'translation_tab') and self.translation_tab:
                tt = self.translation_tab
                try:
                    if hasattr(tt, 'translation_log_viewer') and tt.translation_log_viewer:
                        tt.translation_log_viewer.stop_tail(drain=False)
                except Exception:
                    pass

                try:
                    if hasattr(tt, 'translation_worker') and tt.translation_worker and tt.translation_worker.isRunning():
                        tt.translation_worker.stop()
                        if not tt.translation_worker.wait(2000):
                            try:
                                tt.translation_worker.terminate()
                                tt.translation_worker.wait(500)
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass

        try:
            self.stop_all_background_threads()
        except Exception:
            pass

        event.accept()

    def setup_font_scaling(self):
        """Set up font scaling based on configuration."""
        try:
            app = QApplication.instance()
            initial_scale = (
                app.property("_dazed_initial_font_scale") if app else None
            )
            font_scale = (
                float(initial_scale)
                if initial_scale is not None
                else configured_font_scale()
            )
            self.apply_font_scaling(
                font_scale,
                application_preconfigured=initial_scale is not None,
            )
            
        except Exception as e:
            print(f"Warning: Could not apply font scaling: {e}")
            
    def apply_font_scaling(
        self, scale_factor, *, application_preconfigured: bool = False
    ):
        """Apply font scaling to the entire application."""
        try:
            scale_factor = max(0.5, min(3.0, float(scale_factor)))
            app = QApplication.instance()
            if not app:
                return

            if not application_preconfigured:
                # Runtime scale changes still need to update existing widgets.
                # Startup applies these application-wide values before widgets
                # are constructed, avoiding a full repolish of the UI tree.
                font = app.font()
                font.setPointSize(max(6, int(9 * scale_factor)))
                app.setFont(font)

                from gui.theme import application_stylesheet, scaled_stylesheet

                app.setStyleSheet(
                    scaled_stylesheet(application_stylesheet(), scale_factor)
                )
            else:
                font = app.font()

            # Keep line edits / combos tall enough for the scaled font.
            from PyQt5.QtGui import QFontMetrics
            from PyQt5.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox
            from gui.ui_components import normalize_default_layout_tokens

            control_h = max(32, QFontMetrics(font).height() + 14)
            widgets = app.allWidgets()
            for widget in widgets:
                if isinstance(widget, (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox)):
                    widget.setMinimumHeight(control_h)

            # Scale inline font-size values in every widget's individual stylesheet.
            # We store the *original* stylesheet on each widget (using a Qt property)
            # so that re-scaling always starts from the unmodified values.
            for widget in widgets:
                original = widget.property("_orig_stylesheet")
                if original is None:
                    ss = widget.styleSheet()
                    if not ss or 'font-size' not in ss:
                        continue
                    widget.setProperty("_orig_stylesheet", ss)
                    original = ss

                scaled = re.sub(
                    r'font-size:\s*(\d+(?:\.\d+)?)px',
                    lambda m: f'font-size: {max(6, round(float(m.group(1)) * scale_factor))}px',
                    original
                )
                if scaled != widget.styleSheet():
                    widget.setStyleSheet(scaled)

            normalize_default_layout_tokens(widgets)

            # Font changes can make an otherwise wide workflow rail clip even
            # when the window geometry itself did not change. Re-evaluate the
            # responsive shell immediately instead of waiting for a resize.
            for workflow in (
                getattr(self, "workflow_tab", None),
                getattr(self, "wolf_workflow_tab", None),
            ):
                update_shell = getattr(workflow, "_update_responsive_shell", None)
                if callable(update_shell):
                    update_shell()
                    continue
                rail = getattr(workflow, "_step_rail", None)
                if rail is not None:
                    rail.set_compact(
                        workflow.width() < 1320
                        or rail.labels_require_compact_mode()
                    )
            config_tab = getattr(self, "config_tab", None)
            update_labels = getattr(config_tab, "_update_general_label_width", None)
            if callable(update_labels):
                update_labels()
            image_manager = getattr(self, "image_manager_tab", None)
            arrange_image_actions = getattr(
                image_manager, "_arrange_action_bar", None
            )
            if callable(arrange_image_actions):
                arrange_image_actions()
            update_image_layout = getattr(
                image_manager, "_update_page_scroll_extent", None
            )
            if callable(update_image_layout):
                update_image_layout()

            # Update window title only when non-default scale is active
            if scale_factor != 1.0:
                self.setWindowTitle(f"{APP_NAME} - Visual Translation Interface (Font: {scale_factor:.1f}x)")
            else:
                self.setWindowTitle(f"{APP_NAME} - Visual Translation Interface")
            self._applied_font_scale = scale_factor

        except Exception as e:
            print(f"Warning: Could not apply font scaling: {e}")
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle(f"{APP_NAME} - Visual Translation Interface")
        
        # Get screen geometry and set window size more responsively
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        
        # Set window size to 80% of screen size, with reasonable minimums
        window_width = max(1200, int(screen_geometry.width() * 0.8))
        window_height = max(800, int(screen_geometry.height() * 0.8))
        
        # Center the window on screen
        x = (screen_geometry.width() - window_width) // 2
        y = (screen_geometry.height() - window_height) // 2
        
        self.setGeometry(x, y, window_width, window_height)
        
        # Set minimum size to prevent the window from becoming too small
        self.setMinimumSize(1000, 600)
        
        app_icon = load_application_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main layout with VSCode-style sidebar
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create sidebar for navigation
        from gui.theme import Geometry

        sidebar = QWidget()
        sidebar.setObjectName("appSidebar")
        sidebar.setFixedWidth(Geometry.APP_RAIL_WIDTH)
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(0, 8, 0, 8)
        sidebar_layout.setSpacing(4)
        
        # Create navigation buttons
        self.nav_buttons = []

        # Guide / Quickstart (first - default on open)
        btn_guide = self.create_nav_button("📖", "Guide")
        btn_guide.setToolTip("Guide - beginner setup, full walkthrough, and reference help")
        btn_guide.clicked.connect(lambda: self.switch_page(self.PAGE_GUIDE))
        sidebar_layout.addWidget(btn_guide)
        self.nav_buttons.append(btn_guide)

        # Workflow / Automation
        btn_workflow = self.create_nav_button("⚡", "Workflow")
        btn_workflow.setToolTip("Workflow - automated translation pipeline")
        btn_workflow.clicked.connect(lambda: self.switch_page(self.PAGE_WORKFLOW))
        sidebar_layout.addWidget(btn_workflow)
        self.nav_buttons.append(btn_workflow)

        # RPG Maker image decryption / patch selection
        btn_images = self.create_nav_button("🖼", "Images")
        btn_images.setToolTip("Images - prepare, preview, and patch engine image assets")
        btn_images.clicked.connect(lambda: self.switch_page(self.PAGE_IMAGES))
        sidebar_layout.addWidget(btn_images)
        self.nav_buttons.append(btn_images)

        # Git-backed game version workflow
        btn_version_update = self.create_nav_button("⇄", "Version Update")
        btn_version_update.setToolTip(
            "Version Update - apply exact official Git updates to the translation branch"
        )
        btn_version_update.clicked.connect(
            lambda: self.switch_page(self.PAGE_VERSION_UPDATE)
        )
        sidebar_layout.addWidget(btn_version_update)
        self.nav_buttons.append(btn_version_update)

        # Translation
        btn_translation = self.create_nav_button("🌐", "Translation")
        btn_translation.clicked.connect(lambda: self.switch_page(self.PAGE_TRANSLATION))
        sidebar_layout.addWidget(btn_translation)
        self.nav_buttons.append(btn_translation)

        # Batch history
        btn_batches = self.create_nav_button("📦", "Batches")
        btn_batches.setToolTip("Batches - Anthropic Message Batch history")
        btn_batches.clicked.connect(lambda: self.switch_page(self.PAGE_BATCHES))
        sidebar_layout.addWidget(btn_batches)
        self.nav_buttons.append(btn_batches)

        # Skills
        btn_skills = self.create_nav_button("📚", "Skills")
        btn_skills.setToolTip("Skills - edit system prompt, Project Setup, and translation contexts")
        btn_skills.clicked.connect(lambda: self.switch_page(self.PAGE_SKILLS))
        sidebar_layout.addWidget(btn_skills)
        self.nav_buttons.append(btn_skills)

        # Configuration
        btn_config = self.create_nav_button("⚙️", "Configuration")
        btn_config.clicked.connect(lambda: self.switch_page(self.PAGE_CONFIG))
        sidebar_layout.addWidget(btn_config)
        self.nav_buttons.append(btn_config)

        # Translation model evaluation
        btn_evaluation = self.create_nav_button("⚖", "Evaluation")
        btn_evaluation.setToolTip(
            "Evaluation - blinded, budget-capped translation model comparison"
        )
        btn_evaluation.clicked.connect(
            lambda: self.switch_page(self.PAGE_EVALUATION)
        )
        sidebar_layout.addWidget(btn_evaluation)
        self.nav_buttons.append(btn_evaluation)
        
        sidebar_layout.addStretch()

        # Update button at the bottom of the sidebar
        self.btn_update = self.create_nav_button(self._update_icon, "Check for Updates")
        self.btn_update.setCheckable(False)
        self.btn_update.clicked.connect(self.show_update_dialog)
        sidebar_layout.addWidget(self.btn_update)

        sidebar.setLayout(sidebar_layout)
        
        # Create stacked widget for content pages
        self.content_stack = QStackedWidget()
        
        # Add tabs to stacked widget
        self.setup_tabs()
        
        # Add sidebar and content to main layout
        main_layout.addWidget(sidebar)
        main_layout.addWidget(self.content_stack)
        central_widget.setLayout(main_layout)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Select Guide page by default
        self.switch_page(self.PAGE_GUIDE)
    
    def create_nav_button(self, icon_text, tooltip):
        """Create a navigation button for the sidebar."""
        from gui.platform_glyph import configure_nav_toolbutton

        btn = QToolButton()
        btn.setToolTip(tooltip)
        from gui.theme import Geometry

        btn.setObjectName("appNavButton")
        btn.setAccessibleName(tooltip)
        btn.setFixedSize(Geometry.APP_RAIL_WIDTH, 52)
        btn.setCheckable(True)
        configure_nav_toolbutton(btn, icon_text, horizontal=False)
        return btn
    
    def switch_page(self, index):
        """Switch to the specified page and update button states."""
        if index == self.PAGE_WORKFLOW:
            self._ensure_workflow_container()
        if index == self.PAGE_IMAGES and hasattr(self, "image_manager_tab"):
            self.image_manager_tab.refresh_game_root_from_settings()
        if index == self.PAGE_VERSION_UPDATE and hasattr(self, "version_update_tab"):
            self.version_update_tab.sync_from_workflow()
        self.content_stack.setCurrentIndex(index)
        
        # Update button checked states
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        
    def setup_tabs(self):
        """Set up all the tabs in the interface."""
        self.project_root = PROJECT_ROOT

        # Guide / Quickstart (index 0)
        self.guide_tab = GuideTab(self)
        self.content_stack.addWidget(self.guide_tab)

        # Workflow / Automation (index 1). Both workflow engines are sizeable;
        # construct them only when the user first opens this page.
        self.workflow_tab = None
        self.wolf_workflow_tab = None
        self.workflow_stack = None
        self.workflow_engine_combo = None
        self._workflow_placeholder = QWidget()
        self.content_stack.addWidget(self._workflow_placeholder)

        # Engine-aware Image Manager (index 2)
        self.image_manager_tab = ImageManager(parent=self)
        self.content_stack.addWidget(self.image_manager_tab)

        # Version Update (index 3)
        self.version_update_tab = VersionUpdateTab(parent=self)
        self.content_stack.addWidget(self.version_update_tab)

        # Translation Execution Tab (index 4)
        self.translation_tab = TranslationTab(self)
        self.content_stack.addWidget(self.translation_tab)

        # Batch History Tab (index 4)
        self.batch_tab = BatchTab(self)
        self.content_stack.addWidget(self.batch_tab)

        # Skills Tab (index 5)
        self.skills_tab = SkillsTab(self)
        self.content_stack.addWidget(self.skills_tab)

        # Configuration Tab (index 6)
        self.config_tab = ConfigTab()
        self.config_tab.config_changed.connect(self.on_config_changed)
        self.content_stack.addWidget(self.config_tab)

        # Translation Evaluation Tab (index 8)
        self.evaluation_tab = EvaluationTab(self)
        self.content_stack.addWidget(self.evaluation_tab)

    def _create_workflow_container(self) -> QWidget:
        """Wrap the RPGMaker and Wolf guided workflows behind an engine selector."""
        from gui.workflow_tab import WorkflowTab
        from gui.wolf_workflow_tab import WolfWorkflowTab

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Engine selector bar ──
        bar = QWidget()
        bar.setObjectName("workflowEngineBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(16, 8, 16, 8)
        bar_layout.setSpacing(8)

        engine_label = QLabel("Engine:")
        engine_label.setObjectName("workflowEngineLabel")
        bar_layout.addWidget(engine_label)

        self.workflow_engine_combo = QComboBox()
        self.workflow_engine_combo.setObjectName("workflowEngineSelector")
        self.workflow_engine_combo.addItem("RPG Maker (MV/MZ/Ace)")
        self.workflow_engine_combo.addItem("Wolf RPG (WolfDawn)")
        bar_layout.addWidget(self.workflow_engine_combo)
        bar_layout.addStretch()
        layout.addWidget(bar)

        # ── Stacked guided panels ──
        self.workflow_stack = QStackedWidget()
        self.workflow_tab = WorkflowTab(self)
        self.wolf_workflow_tab = WolfWorkflowTab(self)
        self.workflow_stack.addWidget(self.workflow_tab)
        self.workflow_stack.addWidget(self.wolf_workflow_tab)
        layout.addWidget(self.workflow_stack, 1)

        self.workflow_engine_combo.currentIndexChanged.connect(
            self.workflow_stack.setCurrentIndex
        )
        return container

    def _ensure_workflow_container(self) -> None:
        """Replace the workflow placeholder with the real page exactly once."""
        if self.workflow_tab is not None:
            return
        placeholder = self.content_stack.widget(self.PAGE_WORKFLOW)
        container = self._create_workflow_container()
        self.content_stack.removeWidget(placeholder)
        self.content_stack.insertWidget(self.PAGE_WORKFLOW, container)
        placeholder.deleteLater()

        # Application-level font and QSS were set before startup construction.
        # Apply the remaining per-widget layout and legacy style adjustments to
        # this newly created subtree.
        scale = self._applied_font_scale or configured_font_scale()
        widgets = [container, *container.findChildren(QWidget)]
        from PyQt5.QtGui import QFontMetrics
        from PyQt5.QtWidgets import QDoubleSpinBox, QLineEdit, QSpinBox
        from gui.ui_components import normalize_default_layout_tokens

        control_h = max(
            32,
            QFontMetrics(QApplication.instance().font()).height() + 14,
        )
        for widget in widgets:
            if isinstance(
                widget,
                (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox),
            ):
                widget.setMinimumHeight(control_h)
        normalize_default_layout_tokens(widgets)

        if scale != 1.0:
            for widget in widgets:
                original = widget.property("_orig_stylesheet")
                if original is None:
                    original = widget.styleSheet()
                    if not original or "font-size" not in original:
                        continue
                    widget.setProperty("_orig_stylesheet", original)
                scaled = re.sub(
                    r"font-size:\s*(\d+(?:\.\d+)?)px",
                    lambda match: (
                        f"font-size: {max(6, round(float(match.group(1)) * scale))}px"
                    ),
                    original,
                )
                if scaled != widget.styleSheet():
                    widget.setStyleSheet(scaled)

    def start_background_update_check(self):
        """Check for DazedTL updates after the GUI is visible."""
        if self._update_check_thread and self._update_check_thread.isRunning():
            return
        self._update_check_thread = BackgroundUpdateCheckThread(self)
        self._update_check_thread.checked.connect(self._on_background_update_check)
        self._update_check_thread.start()

    def _on_background_update_check(self, tool_sha: str | None, error: str):
        self._update_check_error = error
        self._pending_tool_sha = tool_sha
        if error:
            self.set_update_check_failed_indicator()
        elif tool_sha:
            self.set_update_indicator()
        else:
            self.clear_update_indicator()

    def set_update_indicator(self):
        """Highlight the update button when updates are available."""
        if not self.btn_update:
            return
        self.btn_update.setToolTip("Updates available — click to install")
        from gui.platform_glyph import configure_nav_toolbutton
        configure_nav_toolbutton(
            self.btn_update, self._update_icon, horizontal=False, update_available=True,
        )

    def clear_update_indicator(self):
        """Restore the default update button appearance."""
        self._pending_tool_sha = None
        self._update_check_error = ""
        if not self.btn_update:
            return
        self.btn_update.setToolTip("Check for Updates")
        from gui.platform_glyph import configure_nav_toolbutton
        configure_nav_toolbutton(
            self.btn_update, self._update_icon, horizontal=False, update_available=False,
        )

    def set_update_check_failed_indicator(self):
        """Explain that update availability could not be verified."""
        if not self.btn_update:
            return
        self.btn_update.setToolTip("Update check failed — click to retry")
        from gui.platform_glyph import configure_nav_toolbutton
        configure_nav_toolbutton(
            self.btn_update,
            self._update_icon,
            horizontal=False,
            update_available=False,
        )

    def show_update_dialog(self):
        """Open the update dialog and check for a newer version."""
        dlg = UpdateDialog(self, pending_tool_sha=self._pending_tool_sha)
        dlg.start()
        dlg.exec_()
        self._pending_tool_sha = dlg._pending_tool_sha
        self._update_check_error = dlg._check_error
        if self._update_check_error:
            self.set_update_check_failed_indicator()
        elif self._pending_tool_sha:
            self.set_update_indicator()
        else:
            self.clear_update_indicator()

    def on_config_changed(self):
        """Handle configuration changes."""
        # This will be called when font scale or other settings change
        try:
            config = self.config_tab.get_config()
            font_scale = config.get("font_scale", 1.0)
            if self._applied_font_scale != float(font_scale):
                self.apply_font_scaling(font_scale)
            for tab in (self.translation_tab, self.workflow_tab, self.wolf_workflow_tab):
                refresh_mode = getattr(tab, "refresh_default_translation_mode", None)
                if callable(refresh_mode):
                    refresh_mode()
                refresh_widths = getattr(tab, "refresh_wrap_widths_from_env", None)
                if callable(refresh_widths):
                    refresh_widths()
            if hasattr(self, "evaluation_tab"):
                self.evaluation_tab._refresh_keys()
        except Exception as e:
            print(f"Warning: Could not apply configuration changes: {e}")
            
    def set_font_scale(self, scale_factor):
        """Set the font scale and update the configuration."""
        try:
            # Apply the scaling immediately
            self.apply_font_scaling(scale_factor)
            
            # Update the configuration tab if it provides a font_scale widget
            try:
                if hasattr(self.config_tab, "font_scale_spin"):
                    self.config_tab.font_scale_spin.setValue(scale_factor)
            except Exception:
                # If the widget isn't present or fails to update, continue silently
                pass

            # Save to .env file if the config tab provides save functionality
            try:
                if hasattr(self.config_tab, "save_to_env"):
                    self.config_tab.save_to_env()
            except Exception:
                pass
            
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Failed to set font scale: {str(e)}")
        
    def create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('File')
        
        # Load project action
        load_action = file_menu.addAction('Load Project')
        load_action.triggered.connect(self.load_project)
        
        # Save project action
        save_action = file_menu.addAction('Save Project')
        save_action.triggered.connect(self.save_project)
        
        file_menu.addSeparator()
        
        # Exit action
        exit_action = file_menu.addAction('Exit')
        exit_action.triggered.connect(self.close)
        
        # Tools menu
        tools_menu = menubar.addMenu('Tools')
        
    # Font Size submenu removed — font scaling menu was unreliable and has been removed
        
        tools_menu.addSeparator()

        # Check for updates
        update_action = tools_menu.addAction('Check for Updates')
        update_action.triggered.connect(self.show_update_dialog)

        tools_menu.addSeparator()
        
        # Reset to defaults
        reset_action = tools_menu.addAction('Reset to Defaults')
        reset_action.triggered.connect(self.reset_to_defaults)
        
        # Validate configuration
        validate_action = tools_menu.addAction('Validate Configuration')
        validate_action.triggered.connect(self.validate_configuration)
        
        # Help menu
        help_menu = menubar.addMenu('Help')

        getting_started_action = help_menu.addAction('Getting Started')
        getting_started_action.triggered.connect(
            lambda: self.switch_page(self.PAGE_GUIDE)
        )

        help_menu.addSeparator()

        # About action
        about_action = help_menu.addAction('About')
        about_action.triggered.connect(self.show_about)
        
    def setup_status_bar(self):
        """Set up the status bar (removed to save space)."""
        # Status bar removed to maximize space for content
        pass
        
    def load_project(self):
        """Load a project configuration."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Load Project Configuration", 
            "", 
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                # Load configuration from file
                self.config_tab.load_from_file(file_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load project:\n{str(e)}")
                
    def save_project(self):
        """Save the current project configuration."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, 
            "Save Project Configuration", 
            "", 
            "JSON Files (*.json);;All Files (*)"
        )
        
        if file_path:
            try:
                # Save configuration to file
                config_data = self.config_tab.get_config()
                
                import json
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(config_data, f, indent=2, ensure_ascii=False)
                    
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save project:\n{str(e)}")
                
    def reset_to_defaults(self):
        """Reset all configurations to default values."""
        reply = QMessageBox.question(
            self, 
            "Reset to Defaults", 
            "Are you sure you want to reset all settings to their default values?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.config_tab.reset_to_defaults()
            
    def validate_configuration(self):
        """Validate the current configuration."""
        try:
            # Validate configuration settings
            config_valid = self.config_tab.validate()
            
            if config_valid:
                QMessageBox.information(self, "Validation", "Configuration is valid!")
            else:
                QMessageBox.warning(self, "Validation", "Configuration has issues. Check the warnings.")
                
        except Exception as e:
            QMessageBox.critical(self, "Validation Error", f"Failed to validate configuration:\n{str(e)}")
            
    def show_about(self):
        """Show the about dialog."""
        QMessageBox.about(
            self, 
            f"About {APP_NAME}",
            f"""
            <h3>{APP_NAME}</h3>
            <p>An AI translation tool for visual novels, RPG games, and other text-based content.</p>
            <p><b>Features:</b></p>
            <ul>
                <li>Guided Workflow for RPG Maker and WolfDawn</li>
                <li>Visual configuration management</li>
                <li>Real-time translation monitoring</li>
                <li>File management and organization</li>
            </ul>
            """
        )
        
    def update_status(self, message):
        """Update the status bar message (removed to save space)."""
        pass
        
    def show_progress(self, show=True):
        """Show or hide the progress bar (removed to save space)."""
        pass
        
    def set_progress(self, value):
        """Set the progress bar value (removed to save space)."""
        pass


def main():
    """Main entry point for the GUI application."""
    try:
        # Enable high DPI scaling before creating QApplication
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        
        # Additional DPI handling for better compatibility
        if hasattr(Qt, 'AA_DisableWindowContextHelpButton'):
            QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)
            
        # Set high DPI scale factor policy
        if hasattr(QApplication, 'setHighDpiScaleFactorRoundingPolicy'):
            QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

        if sys.platform.startswith("linux"):
            from util.linux_desktop import ensure_linux_desktop_entry, install_qt_message_filter

            install_qt_message_filter()
            ensure_linux_desktop_entry()
            QGuiApplication.setDesktopFileName(APP_NAME)

        QCoreApplication.setOrganizationName(ORG_NAME)
        QCoreApplication.setApplicationName(APP_NAME)
        migrate_app_settings()
        
        app = QApplication(sys.argv)
        app.setStyle("Fusion")

        # Windows taskbar groups by executable (python.exe) unless we set an explicit
        # AppUserModelID; combine with QApplication window icon so the pinned icon
        # matches the window instead of the Python launcher.
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    f"{ORG_NAME}.{APP_NAME}.1"
                )
            except Exception:
                pass

        app_icon = load_application_icon()
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
        
        # Additional screen-aware settings
        screen = app.primaryScreen()
        if screen:
            dpi = screen.logicalDotsPerInch()
            print(f"Screen DPI: {dpi}")
            
    except Exception as e:
        print(f"Failed to create QApplication: {e}")
        print("Make sure PyQt5 is properly installed:")
        print("  pip install PyQt5>=5.15.0")
        return 1
    
    # Set application properties
    app.setApplicationVersion("1.0")
    
    # Apply the canonical dark palette and QSS after QApplication exists.
    from gui.theme import apply_application_theme

    initial_font_scale = configured_font_scale()
    font = app.font()
    font.setPointSize(max(6, int(9 * initial_font_scale)))
    app.setFont(font)
    apply_application_theme(app, font_scale=initial_font_scale)
    app.setProperty("_dazed_initial_font_scale", initial_font_scale)

    try:
        # Create and show the main window
        window = DazedMTLGUI()
        window.show()

        # Safety: ensure any running translation worker is stopped when the
        # application is quitting (aboutToQuit). This helps guarantee the
        # ThreadPoolExecutor threads and subprocesses are shut down so the
        # Python interpreter can exit cleanly.
        def _on_about_to_quit():
            try:
                window.stop_all_background_threads()
            except Exception:
                pass

        try:
            app.aboutToQuit.connect(_on_about_to_quit)
        except Exception:
            pass
        
        # Show font adjustment tip on first run (optional)
        try:
            from dotenv import load_dotenv
            load_dotenv()
            show_font_tip = os.getenv("show_font_tip", "true").lower() == "true"
            
            if show_font_tip:
                QMessageBox.information(
                    window,
                    "Font Size Adjustment",
                    "💡 Font too small?\n\n"
                    "• Use Tools → Font Size menu for quick adjustment\n"
                    "• Or go to Configuration tab → UI Settings\n"
                    "• Try 'Large (1.5x)' or 'Extra Large (2.0x)' for high DPI displays\n\n"
                    "This tip can be disabled in the Configuration tab."
                )
                
                # Set flag to not show again
                from dotenv import set_key
                set_key(".env", "show_font_tip", "false")
                
        except Exception:
            pass  # Ignore if .env operations fail
        
        # Start the application
        return app.exec_()
    except Exception as e:
        print(f"Error starting GUI: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
