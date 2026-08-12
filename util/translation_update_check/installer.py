"""Install TranslationUpdateCheck into an RPG Maker MV or MZ game."""

from __future__ import annotations

import re
from pathlib import Path


PLUGIN_NAME = "TranslationUpdateCheck"
PLUGIN_ENTRY = (
    '        { "name": "TranslationUpdateCheck", "status": true, '
    '"description": "Translation update warning", "parameters": {} }'
)
DEFAULT_PLUGIN_SRC = (
    Path(__file__).resolve().parents[2]
    / "gameupdate"
    / "gameupdate"
    / f"{PLUGIN_NAME}.js"
)


def _detect_engine(game_root: Path) -> tuple[str, Path, Path] | None:
    root = Path(game_root)
    mv_plugins = root / "www" / "js" / "plugins.js"
    mz_plugins = root / "js" / "plugins.js"
    if mv_plugins.is_file():
        return "MV", mv_plugins, root / "www" / "js" / "plugins"
    if mz_plugins.is_file():
        return "MZ", mz_plugins, root / "js" / "plugins"
    return None


def _declared(content: str) -> bool:
    return bool(re.search(r'"name"\s*:\s*"TranslationUpdateCheck"', content))


def install(game_root: str | Path) -> tuple[bool, str]:
    """Copy and enable the checker. Repeated installs leave one declaration."""
    detected = _detect_engine(Path(game_root))
    if detected is None:
        return False, "Translation update check skipped (not an RPG Maker MV/MZ game)."
    engine, plugins_js, plugins_dir = detected
    if not DEFAULT_PLUGIN_SRC.is_file():
        return False, f"Translation update checker not found: {DEFAULT_PLUGIN_SRC}"

    try:
        content = plugins_js.read_text(encoding="utf-8")
        newline = "\r\n" if "\r\n" in content else "\n"
        list_end = content.rfind("];")
        if not _declared(content) and list_end < 0:
            return False, "Could not find the plugin list end in plugins.js."

        plugins_dir.mkdir(parents=True, exist_ok=True)
        target = plugins_dir / f"{PLUGIN_NAME}.js"
        target.write_bytes(DEFAULT_PLUGIN_SRC.read_bytes())

        if not _declared(content):
            before = content[:list_end].rstrip()
            separator = newline if before.endswith(",") else "," + newline
            content = before + separator + PLUGIN_ENTRY + newline + "    " + content[list_end:]
            plugins_js.write_text(content, encoding="utf-8", newline="")
    except Exception as exc:
        return False, f"Could not install translation update check: {exc}"

    return True, f"Translation update check installed for RPG Maker {engine}."
