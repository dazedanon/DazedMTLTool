"""Install/update the Linux .desktop entry for taskbar and window icons."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from util.paths import APP_NAME, ICON_PATH, LEGACY_APP_NAME, PROJECT_ROOT

DESKTOP_ID = APP_NAME
LAUNCH_SCRIPT = PROJECT_ROOT / "scripts" / "launch.sh"

# Qt logs this on Wayland whenever a dialog tries to steal focus (harmless noise).
_WAYLAND_ACTIVATE_WARNING = "Wayland does not support QWindow::requestActivate()"


def _append_qt_logging_rule(rule: str) -> None:
    category = rule.split("=", 1)[0]
    existing = os.environ.get("QT_LOGGING_RULES", "")
    if category in existing:
        return
    os.environ["QT_LOGGING_RULES"] = f"{existing};{rule}" if existing else rule


def configure_qt_platform() -> None:
    """Apply Linux/Qt environment tweaks before constructing QApplication."""
    if not sys.platform.startswith("linux"):
        return
    _append_qt_logging_rule("qt.qpa.wayland=false")


def install_qt_message_filter() -> None:
    """Drop the noisy Wayland requestActivate warning (QT rules miss some builds)."""
    if not sys.platform.startswith("linux"):
        return
    try:
        from PyQt5.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return

    def _handler(mode, _context, message):
        if _WAYLAND_ACTIVATE_WARNING in message:
            return
        if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            print(message, file=sys.stderr)

    qInstallMessageHandler(_handler)


def installed_desktop_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME", "")
    if data_home:
        base = Path(data_home)
    else:
        base = Path.home() / ".local" / "share"
    return base / "applications" / f"{DESKTOP_ID}.desktop"


def _desktop_content(root: Path, icon: Path, launch: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={DESKTOP_ID}\n"
        "GenericName=AI Translation Tool\n"
        "Comment=AI translation tool for visual novels and RPG games\n"
        f"Exec={launch}\n"
        f"Icon={icon}\n"
        f"Path={root}\n"
        "Terminal=false\n"
        "Categories=Development;Utility;\n"
        f"StartupWMClass={DESKTOP_ID}\n"
    )


def ensure_linux_desktop_entry() -> None:
    """Write ~/.local/share/applications/DazedTL.desktop with absolute paths."""
    if not sys.platform.startswith("linux"):
        return
    if not LAUNCH_SCRIPT.is_file() or not ICON_PATH.is_file():
        return

    desktop_path = installed_desktop_path()
    content = _desktop_content(PROJECT_ROOT, ICON_PATH, LAUNCH_SCRIPT)

    try:
        legacy = desktop_path.parent / f"{LEGACY_APP_NAME}.desktop"
        if legacy.is_file() and legacy.resolve() != desktop_path.resolve():
            try:
                legacy.unlink()
            except OSError:
                pass

        if desktop_path.is_file() and desktop_path.read_text(encoding="utf-8") == content:
            return
        desktop_path.parent.mkdir(parents=True, exist_ok=True)
        desktop_path.write_text(content, encoding="utf-8")
        desktop_path.chmod(0o755)
    except OSError as exc:
        print(f"Warning: could not install Linux desktop entry ({exc})")
        return

    _refresh_desktop_database(desktop_path.parent)


def _refresh_desktop_database(applications_dir: Path) -> None:
    for cmd in (
        ["update-desktop-database", str(applications_dir)],
        ["kbuildsycoca5", "--noincremental"],
    ):
        try:
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
