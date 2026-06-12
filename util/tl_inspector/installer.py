"""Install / uninstall TLInspector into an RPG Maker MV or MZ game folder.

Credits: Idea by Sakura · Plugin by kaoss
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

PLUGIN_NAME = "TLInspector"
PLUGIN_ENTRY = (
    '        { "name": "TLInspector", "status": true, '
    '"description": "TL source inspector", "parameters": {} }'
)

_PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_PLUGIN_SRC = _PKG_ROOT / "TLInspector.js"


def bundled_plugin_path() -> Path:
    return DEFAULT_PLUGIN_SRC


def detect_engine(game_root: Path) -> tuple[str, Path, Path] | None:
    """Return (engine, plugins_js, plugins_dir) or None if not MV/MZ."""
    root = Path(game_root)
    mv_js = root / "www" / "js" / "plugins.js"
    mz_js = root / "js" / "plugins.js"
    if mv_js.is_file():
        return "MV", mv_js, root / "www" / "js" / "plugins"
    if mz_js.is_file():
        return "MZ", mz_js, root / "js" / "plugins"
    return None


def _read_plugins_js(plugins_js: Path) -> tuple[str, str]:
    content = plugins_js.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in content else "\n"
    return content, nl


def _is_declared(content: str) -> bool:
    return bool(re.search(r'"name"\s*:\s*"TLInspector"', content))


def status(game_root: Path) -> dict:
    """Return install state for the game folder."""
    info = detect_engine(game_root)
    if info is None:
        return {
            "ok": False,
            "engine": None,
            "installed": False,
            "declared": False,
            "plugin_file": None,
            "message": "No RPG Maker MV/MZ game found (missing plugins.js).",
        }
    engine, plugins_js, plugins_dir = info
    target = plugins_dir / f"{PLUGIN_NAME}.js"
    content, _ = _read_plugins_js(plugins_js)
    declared = _is_declared(content)
    file_there = target.is_file()
    return {
        "ok": True,
        "engine": engine,
        "installed": declared or file_there,
        "declared": declared,
        "plugin_file": file_there,
        "plugins_js": str(plugins_js),
        "target": str(target),
        "message": (
            "Installed"
            if declared and file_there
            else "Partially installed"
            if declared or file_there
            else "Not installed"
        ),
    }


def install(game_root: Path, source_js: Path | None = None) -> tuple[bool, str]:
    """Copy TLInspector.js into the game and declare it in plugins.js."""
    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."

    engine, plugins_js, plugins_dir = info
    src = Path(source_js) if source_js else DEFAULT_PLUGIN_SRC
    if not src.is_file():
        return False, f"TLInspector.js not found: {src}"

    target = plugins_dir / f"{PLUGIN_NAME}.js"
    content, nl = _read_plugins_js(plugins_js)

    plugins_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)

    if not _is_declared(content):
        idx = content.rfind("];")
        if idx < 0:
            return False, "Could not find plugin list end ( ]; ) in plugins.js."
        before = content[:idx].rstrip()
        after = content[idx:]
        sep = nl if before.endswith(",") else "," + nl
        content = before + sep + PLUGIN_ENTRY + nl + "    " + after
        plugins_js.write_text(content, encoding="utf-8", newline="")

    return True, f"TLInspector installed for RPG Maker {engine}. Press F10 in-game to open."


def uninstall(game_root: Path) -> tuple[bool, str]:
    """Remove TLInspector from plugins.js and delete the plugin file."""
    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."

    _, plugins_js, plugins_dir = info
    target = plugins_dir / f"{PLUGIN_NAME}.js"
    content, nl = _read_plugins_js(plugins_js)

    if _is_declared(content):
        kept = [
            line for line in re.split(r"\r?\n", content)
            if not re.search(r'"name"\s*:\s*"TLInspector"', line)
        ]
        new_text = nl.join(kept)
        new_text = re.sub(r",(\s*)\];", r"\1];", new_text)
        plugins_js.write_text(new_text, encoding="utf-8", newline="")

    if target.is_file():
        target.unlink()

    return True, "TLInspector uninstalled."
