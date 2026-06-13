"""Forge plugin build — hotkey (and MZ UI scale) injection at install time."""

from __future__ import annotations

import json
import re
from pathlib import Path

from util.playtest.config import load_config

_PKG_ROOT = Path(__file__).resolve().parent

PLUGIN_BY_ENGINE = {
    "MV": "Forge_MV",
    "MZ": "Forge_MZ",
}


def bundled_plugin_path(engine: str) -> Path:
    name = PLUGIN_BY_ENGINE.get(engine)
    if not name:
        raise ValueError(f"Unsupported engine: {engine}")
    return _PKG_ROOT / f"{name}.js"


def _js_literal(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def plugin_entry(engine: str, hotkey: str, ui_scale: str = "auto") -> str:
    hk = _js_literal(hotkey.strip() or "F10")
    name = PLUGIN_BY_ENGINE[engine]
    if engine == "MZ":
        scale = _js_literal(ui_scale.strip() or "auto")
        return (
            f'        {{ "name": "{name}", "status": true, '
            f'"description": "Forge — in-game cheat & editor overlay", '
            f'"parameters": {{ "hotkey": {hk}, "speedKey": "Control", '
            f'"startOpen": "false", "itemMaxOverride": "0", "uiScale": {scale} }} }}'
        )
    return (
        f'        {{ "name": "{name}", "status": true, '
        f'"description": "Forge — in-game cheat & editor overlay", '
        f'"parameters": {{ "Hotkey": {hk}, "SpeedKey": "Control", '
        f'"StartOpen": "false", "ItemMaxOverride": "0" }} }}'
    )


def _patch_forge_hotkey(forge_text: str, hotkey: str, engine: str) -> str:
    hk = hotkey.strip() or "F10"
    if engine == "MZ":
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

    pattern = (
        r"(\* @param Hotkey\s*\n"
        r"(?:\s*\*[^\n]*\n)*?"
        r"\s*\* @default )F10"
    )
    forge_text, n = re.subn(pattern, rf"\g<1>{hk}", forge_text, count=1)
    if n == 0:
        raise ValueError("Could not patch @default Hotkey in Forge_MV.js")
    forge_text = re.sub(r"\(P\.Hotkey \|\| 'F10'\)", f"(P.Hotkey || '{hk}')", forge_text)
    return forge_text


def prepare_forge_js(engine: str, source: Path | None = None, cfg: dict | None = None) -> str:
    """Build Forge_MV.js or Forge_MZ.js with configured hotkey (and MZ UI scale)."""
    src = source or bundled_plugin_path(engine)
    effective = {**load_config(), **(cfg or {})}
    text = _patch_forge_hotkey(src.read_text(encoding="utf-8"), effective["forgeHotkey"], engine)
    if engine != "MZ":
        return text

    scale = effective.get("uiScale", "auto")
    text, n = re.subn(
        r"(\* @param uiScale\s*\n(?:\s*\*[^\n]*\n)*?\s*\* @default )auto",
        rf"\g<1>{scale}",
        text,
        count=1,
    )
    if n == 0:
        raise ValueError("Could not patch @default uiScale in Forge_MZ.js")
    text = re.sub(r"\(P\.uiScale \|\| 'auto'\)", f"(P.uiScale || '{scale}')", text)
    return text


# Back-compat alias
def prepare_forge_mz_js(source: Path | None = None, cfg: dict | None = None) -> str:
    return prepare_forge_js("MZ", source, cfg)
