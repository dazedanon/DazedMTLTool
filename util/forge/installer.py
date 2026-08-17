"""Install / uninstall Forge into an RPG Maker MV or MZ game folder.

Credits: len — https://gitgud.io/zero64801/forge-mvmz (Forge plugin)
"""

from __future__ import annotations

import re
from pathlib import Path

from util.forge.config import (
    PLUGIN_BY_ENGINE,
    is_legacy_forge_plugin,
    plugin_entry,
    prepare_forge_js,
)
from util.paths import (
    GameProjectPathError,
    ensure_game_tool_gitignore,
    game_metadata_dir,
)
from util.rpgmaker_plugin_registry import (
    atomic_write_text,
    install_plugin_files,
    update_plugin_entry,
)

_PKG_ROOT = Path(__file__).resolve().parent


def bundled_plugin_path(engine: str) -> Path:
    from util.forge.config import bundled_plugin_path as _path

    return _path(engine)


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


def detect_mz(game_root: Path) -> tuple[Path, Path] | None:
    """Return (plugins_js, plugins_dir) for MZ only, or None."""
    info = detect_engine(game_root)
    if info is None or info[0] != "MZ":
        return None
    return info[1], info[2]


def _plugin_name(engine: str) -> str:
    return PLUGIN_BY_ENGINE[engine]


def _prepare_ignored_forge_settings(game_root: Path) -> tuple[bool, str]:
    """Create Forge's runtime metadata home and ensure Git ignores it."""
    try:
        game_metadata_dir(game_root)
        ensure_game_tool_gitignore(game_root)
        game_metadata_dir(game_root, create=True)
    except (OSError, GameProjectPathError) as exc:
        return False, f"Could not prepare ignored Forge settings: {exc}"
    return True, ""


def _read_plugins_js(plugins_js: Path) -> tuple[str, str]:
    content = plugins_js.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in content else "\n"
    return content, nl


def _is_declared(content: str, plugin_name: str) -> bool:
    return bool(re.search(rf'"name"\s*:\s*"{re.escape(plugin_name)}"', content))


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
    plugin_name = _plugin_name(engine)
    target = plugins_dir / f"{plugin_name}.js"
    content, _ = _read_plugins_js(plugins_js)
    declared = _is_declared(content, plugin_name)
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


def install(game_root: Path, source_js: Path | None = None, cfg: dict | None = None) -> tuple[bool, str]:
    """Copy Forge_MV.js or Forge_MZ.js into the game and declare it in plugins.js."""
    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."

    engine, plugins_js, plugins_dir = info
    plugin_name = _plugin_name(engine)
    default_src = bundled_plugin_path(engine)
    source = Path(source_js) if source_js else default_src

    if source_js and not source.is_file():
        return False, f"{plugin_name}.js not found: {source_js}"
    if not source_js and not default_src.is_file():
        return False, f"{plugin_name}.js not found: {default_src}"

    target = plugins_dir / f"{plugin_name}.js"
    hotkey = (cfg or {}).get("forgeHotkey", "F10")
    ui_scale = (cfg or {}).get("uiScale", "auto")
    try:
        content, nl = _read_plugins_js(plugins_js)
        source_text = source.read_text(encoding="utf-8")
        modern = not is_legacy_forge_plugin(source_text)
        entry = plugin_entry(engine, hotkey, ui_scale, modern=modern)
        registry_content = update_plugin_entry(
            content,
            plugin_name,
            entry,
            nl,
            description_prefixes=("Forge",),
        )
        plugin_content = prepare_forge_js(engine, source, cfg)
    except (OSError, ValueError) as exc:
        return False, f"Could not prepare the Forge install: {exc}"

    prepared, message = _prepare_ignored_forge_settings(game_root)
    if not prepared:
        return False, message

    try:
        plugins_dir.mkdir(parents=True, exist_ok=True)
        install_plugin_files(target, plugin_content, plugins_js, registry_content)
    except OSError as exc:
        return False, f"Could not install {plugin_name}: {exc}"

    return True, f"Forge installed for RPG Maker {engine}. Press {hotkey} in-game to open."


def uninstall(game_root: Path) -> tuple[bool, str]:
    """Remove Forge from plugins.js and delete the plugin file."""
    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."

    engine, plugins_js, plugins_dir = info
    plugin_name = _plugin_name(engine)
    target = plugins_dir / f"{plugin_name}.js"
    if target.is_symlink() or (target.exists() and not target.is_file()):
        return False, f"Plugin destination is not a regular file: {target}"

    try:
        content, nl = _read_plugins_js(plugins_js)
        has_remnants = bool(
            re.search(r'"description"\s*:\s*"Forge[^\"]*"', content)
        )
        if _is_declared(content, plugin_name) or has_remnants:
            registry_content = update_plugin_entry(
                content,
                plugin_name,
                None,
                nl,
                description_prefixes=("Forge",),
            )
            atomic_write_text(plugins_js, registry_content)
        if target.is_file():
            target.unlink()
    except (OSError, ValueError) as exc:
        return False, f"Could not uninstall {plugin_name}: {exc}"

    return True, "Forge uninstalled."


def apply_config(game_root: Path, cfg: dict | None = None) -> tuple[bool, str]:
    """Rewrite an installed Forge plugin with current playtest settings."""
    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."

    engine, _, plugins_dir = info
    plugin_name = _plugin_name(engine)
    target = plugins_dir / f"{plugin_name}.js"
    if not target.is_file():
        return False, "Forge is not installed in this game folder."

    prepared, message = _prepare_ignored_forge_settings(game_root)
    if not prepared:
        return False, message

    try:
        atomic_write_text(target, prepare_forge_js(engine, cfg=cfg))
    except (OSError, ValueError) as exc:
        return False, f"Could not apply {plugin_name} settings: {exc}"
    return True, f"Forge settings applied to the installed {plugin_name} plugin."
