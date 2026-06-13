"""Forge_MZ build — hotkey injection at install time."""

from __future__ import annotations

import json
import re
from pathlib import Path

from util.playtest.config import load_config

_PKG_ROOT = Path(__file__).resolve().parent
BUNDLED_PLUGIN = _PKG_ROOT / "Forge_MZ.js"


def _js_literal(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def plugin_entry(hotkey: str) -> str:
    hk = _js_literal(hotkey.strip() or "F10")
    return (
        f'        {{ "name": "Forge_MZ", "status": true, '
        f'"description": "Forge — in-game cheat & editor overlay", '
        f'"parameters": {{ "hotkey": {hk}, "speedKey": "Control", '
        f'"startOpen": "false", "itemMaxOverride": "0" }} }}'
    )


def _patch_forge_hotkey(forge_text: str, hotkey: str) -> str:
    hk = hotkey.strip() or "F10"
    pattern = (
        r"(\* @param hotkey\s*\n"
        r"(?:\s*\*[^\n]*\n)*?"
        r"\s*\* @default )F10"
    )
    forge_text, n = re.subn(pattern, rf"\g<1>{hk}", forge_text, count=1)
    if n == 0:
        raise ValueError("Could not patch @default hotkey in Forge_MZ.js")
    forge_text = re.sub(r"\(P\.hotkey \|\| 'F10'\)", f"(P.hotkey || '{hk}')", forge_text)
    forge_text = re.sub(r"API\._hotkey \|\| 'F10'", f"API._hotkey || '{hk}'", forge_text)
    return forge_text


def prepare_forge_mz_js(source: Path | None = None, cfg: dict | None = None) -> str:
    """Build Forge_MZ.js with the configured toggle hotkey."""
    src = source or BUNDLED_PLUGIN
    effective = {**load_config(), **(cfg or {})}
    return _patch_forge_hotkey(src.read_text(encoding="utf-8"), effective["forgeHotkey"])
