"""Install / uninstall Forge into an RPG Maker MV or MZ game folder.

Credits: len — https://gitgud.io/zero64801/forge-mvmz (Forge plugin)
"""

from __future__ import annotations

import re
from pathlib import Path

from util.forge.config import PLUGIN_BY_ENGINE, plugin_entry, prepare_forge_js

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


def _find_plugin_block_span(content: str, plugin_name: str) -> tuple[int, int] | None:
    """Return [start, end) span of the plugin object in plugins.js, or None."""
    m = re.search(rf'"name"\s*:\s*"{re.escape(plugin_name)}"', content)
    if not m:
        return None
    start = content.rfind("{", 0, m.start())
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(content)):
        ch = content[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                while end < len(content) and content[end] in " \t\r\n":
                    end += 1
                if end < len(content) and content[end] == ",":
                    end += 1
                return start, end
    return None


def _remove_plugin_block(content: str, plugin_name: str) -> str:
    compact = rf"\{{[^{{}}]*\"name\"\s*:\s*\"{re.escape(plugin_name)}\"[^{{}}]*\}}\s*,?"
    content = re.sub(compact, "", content)
    while True:
        span = _find_plugin_block_span(content, plugin_name)
        if span is None:
            break
        start, end = span
        before = content[:start].rstrip()
        after = content[end:].lstrip()
        if before.endswith(","):
            before = before[:-1].rstrip()
        elif after.startswith(","):
            after = after[1:].lstrip()
        gap = "\n" if before and after and not before.endswith("\n") else ""
        content = before + gap + after
    lines = [
        line
        for line in re.split(r"\r?\n", content)
        if not re.search(rf"\"name\"\s*:\s*\"{re.escape(plugin_name)}\"", line)
    ]
    content = "\n".join(lines)
    # Leftover fragments from a previously corrupted multi-line entry.
    content = re.sub(
        r"\{\s*\"status\"\s*:\s*true\s*,\s*\"description\"\s*:\s*\"Forge[^\"]*\""
        r"\s*,\s*\"parameters\"\s*:\s*\{[^{}]*\}\s*\}\s*,?",
        "",
        content,
    )
    return content


def _upsert_plugin_entry(content: str, plugin_name: str, entry: str, nl: str) -> str:
    """Insert or replace a Forge plugin entry in plugins.js."""
    span = _find_plugin_block_span(content, plugin_name)
    if span is not None:
        start, end = span
        before = content[:start].rstrip()
        after = content[end:].lstrip()
        sep = nl if before.endswith(",") or not before else "," + nl
        return before + sep + entry + nl + after
    idx = content.rfind("];")
    if idx < 0:
        raise ValueError("Could not find plugin list end ( ]; ) in plugins.js.")
    before = content[:idx].rstrip()
    after = content[idx:]
    sep = nl if before.endswith(",") else "," + nl
    return before + sep + entry + nl + "    " + after


def install(game_root: Path, source_js: Path | None = None, cfg: dict | None = None) -> tuple[bool, str]:
    """Copy Forge_MV.js or Forge_MZ.js into the game and declare it in plugins.js."""
    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."

    engine, plugins_js, plugins_dir = info
    plugin_name = _plugin_name(engine)
    default_src = bundled_plugin_path(engine)

    if source_js and not Path(source_js).is_file():
        return False, f"{plugin_name}.js not found: {source_js}"
    if not source_js and not default_src.is_file():
        return False, f"{plugin_name}.js not found: {default_src}"

    target = plugins_dir / f"{plugin_name}.js"
    content, nl = _read_plugins_js(plugins_js)

    plugins_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(prepare_forge_js(engine, source_js, cfg), encoding="utf-8")

    hotkey = (cfg or {}).get("forgeHotkey", "F10")
    ui_scale = (cfg or {}).get("uiScale", "auto")
    entry = plugin_entry(engine, hotkey, ui_scale)
    try:
        content = _upsert_plugin_entry(content, plugin_name, entry, nl)
        plugins_js.write_text(content, encoding="utf-8", newline="")
    except ValueError as exc:
        return False, str(exc)

    return True, f"Forge installed for RPG Maker {engine}. Press {hotkey} in-game to open."


def uninstall(game_root: Path) -> tuple[bool, str]:
    """Remove Forge from plugins.js and delete the plugin file."""
    info = detect_engine(game_root)
    if info is None:
        return False, "No RPG Maker MV/MZ game found at that path."

    engine, plugins_js, plugins_dir = info
    plugin_name = _plugin_name(engine)
    target = plugins_dir / f"{plugin_name}.js"
    content, nl = _read_plugins_js(plugins_js)

    if _is_declared(content, plugin_name):
        content = _remove_plugin_block(content, plugin_name)
        content = re.sub(r",(\s*)\];", r"\1];", content)
        plugins_js.write_text(content, encoding="utf-8", newline="")

    if target.is_file():
        target.unlink()

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

    target.write_text(prepare_forge_js(engine, cfg=cfg), encoding="utf-8")
    return True, f"Forge settings applied to the installed {plugin_name} plugin."
