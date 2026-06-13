"""Install / uninstall Forge_MZ into an RPG Maker MZ game folder."""

from __future__ import annotations

import re
from pathlib import Path

from util.forge.config import plugin_entry, prepare_forge_mz_js

PLUGIN_NAME = "Forge_MZ"

_PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_PLUGIN_SRC = _PKG_ROOT / "Forge_MZ.js"


def bundled_plugin_path() -> Path:
    return DEFAULT_PLUGIN_SRC


def detect_mz(game_root: Path) -> tuple[Path, Path] | None:
    """Return (plugins_js, plugins_dir) or None if not MZ."""
    root = Path(game_root)
    mz_js = root / "js" / "plugins.js"
    if mz_js.is_file():
        return mz_js, root / "js" / "plugins"
    return None


def _read_plugins_js(plugins_js: Path) -> tuple[str, str]:
    content = plugins_js.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in content else "\n"
    return content, nl


def _is_declared(content: str) -> bool:
    return bool(re.search(rf'"name"\s*:\s*"{re.escape(PLUGIN_NAME)}"', content))


def status(game_root: Path) -> dict:
    """Return install state for the game folder."""
    info = detect_mz(game_root)
    if info is None:
        return {
            "ok": False,
            "engine": None,
            "installed": False,
            "declared": False,
            "plugin_file": None,
            "message": "No RPG Maker MZ game found (missing js/plugins.js).",
        }
    plugins_js, plugins_dir = info
    target = plugins_dir / f"{PLUGIN_NAME}.js"
    content, _ = _read_plugins_js(plugins_js)
    declared = _is_declared(content)
    file_there = target.is_file()
    return {
        "ok": True,
        "engine": "MZ",
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


def install(game_root: Path, source_js: Path | None = None, cfg: dict | None = None) -> tuple[bool, str]:
    """Copy Forge_MZ.js into the game and declare it in plugins.js."""
    info = detect_mz(game_root)
    if info is None:
        return False, "No RPG Maker MZ game found at that path (Forge is MZ-only)."

    plugins_js, plugins_dir = info
    if source_js and not Path(source_js).is_file():
        return False, f"Forge_MZ.js not found: {source_js}"
    if not source_js and not DEFAULT_PLUGIN_SRC.is_file():
        return False, f"Forge_MZ.js not found: {DEFAULT_PLUGIN_SRC}"

    target = plugins_dir / f"{PLUGIN_NAME}.js"
    content, nl = _read_plugins_js(plugins_js)

    plugins_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(prepare_forge_mz_js(source_js, cfg), encoding="utf-8")

    hotkey = (cfg or {}).get("forgeHotkey", "F10")
    ui_scale = (cfg or {}).get("uiScale", "auto")
    entry = plugin_entry(hotkey, ui_scale)
    if not _is_declared(content):
        idx = content.rfind("];")
        if idx < 0:
            return False, "Could not find plugin list end ( ]; ) in plugins.js."
        before = content[:idx].rstrip()
        after = content[idx:]
        sep = nl if before.endswith(",") else "," + nl
        content = before + sep + entry + nl + "    " + after
        plugins_js.write_text(content, encoding="utf-8", newline="")

    return True, f"Forge installed for RPG Maker MZ. Press {hotkey} in-game to open."


def uninstall(game_root: Path) -> tuple[bool, str]:
    """Remove Forge_MZ from plugins.js and delete the plugin file."""
    info = detect_mz(game_root)
    if info is None:
        return False, "No RPG Maker MZ game found at that path."

    plugins_js, plugins_dir = info
    target = plugins_dir / f"{PLUGIN_NAME}.js"
    content, nl = _read_plugins_js(plugins_js)

    if _is_declared(content):
        kept = [
            line for line in re.split(r"\r?\n", content)
            if not re.search(rf'"name"\s*:\s*"{re.escape(PLUGIN_NAME)}"', line)
        ]
        new_text = nl.join(kept)
        new_text = re.sub(r",(\s*)\];", r"\1];", new_text)
        plugins_js.write_text(new_text, encoding="utf-8", newline="")

    if target.is_file():
        target.unlink()

    return True, "Forge uninstalled."


def apply_config(game_root: Path, cfg: dict | None = None) -> tuple[bool, str]:
    """Rewrite an installed Forge_MZ.js with the current Forge hotkey."""
    info = detect_mz(game_root)
    if info is None:
        return False, "No RPG Maker MZ game found at that path."

    _, plugins_dir = info
    target = plugins_dir / f"{PLUGIN_NAME}.js"
    if not target.is_file():
        return False, "Forge is not installed in this game folder."

    target.write_text(prepare_forge_mz_js(cfg=cfg), encoding="utf-8")
    return True, "Forge hotkey applied to the installed plugin."
