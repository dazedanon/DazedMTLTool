"""Forge plugin build — install-time hotkey and UI scale injection.

Canonical Forge_MV.js / Forge_MZ.js sources stay untouched under ``upstream/``.
Patches are applied in memory when installing or applying settings to a game.

MV uses the pre-rewrite legacy plugin (old NW.js / Chrome ~65).
MZ uses the rewritten unified forge.js bundle.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from util.playtest.config import load_config
from util.forge.scale_patches import apply_ui_scale_patches
from util.forge.modern_patches import apply_modern_forge_patches

_PKG_ROOT = Path(__file__).resolve().parent

PLUGIN_BY_ENGINE = {
    "MV": "Forge_MV",
    "MZ": "Forge_MZ",
}


def bundled_plugin_path(engine: str) -> Path:
    name = PLUGIN_BY_ENGINE.get(engine)
    if not name:
        raise ValueError(f"Unsupported engine: {engine}")
    return _PKG_ROOT / "upstream" / f"{name}.js"


def _js_literal(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def plugin_entry(engine: str, hotkey: str, ui_scale: str = "auto", *, modern: bool = False) -> str:
    name = PLUGIN_BY_ENGINE[engine]
    if modern:
        return (
            f'        {{ "name": "{name}", "status": true, '
            f'"description": "Forge — in-game cheat & editor overlay", '
            f'"parameters": {{}} }}'
        )
    hk = _js_literal(hotkey.strip() or "F10")
    scale = _js_literal(ui_scale.strip() or "auto")
    if engine == "MZ":
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
        f'"StartOpen": "false", "ItemMaxOverride": "0", "UiScale": {scale} }} }}'
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
        return forge_text

    pattern = (
        r"(\* @param Hotkey\s*\n"
        r"(?:\s*\*[^\n]*\n)*?"
        r"\s*\* @default )F10"
    )
    forge_text, n = re.subn(pattern, rf"\g<1>{hk}", forge_text, count=1)
    if n == 0:
        raise ValueError("Could not patch @default Hotkey in Forge_MV.js")
    return forge_text


def _patch_forge_ui_scale_default(forge_text: str, ui_scale: str, engine: str) -> str:
    scale = ui_scale.strip() or "auto"
    if engine == "MZ":
        pattern = r"(\* @param uiScale\s*\n(?:\s*\*[^\n]*\n)*?\s*\* @default )auto"
        if scale != "auto":
            forge_text, n = re.subn(pattern, rf"\g<1>{scale}", forge_text, count=1)
            if n == 0:
                raise ValueError("Could not patch @default uiScale in Forge_MZ.js")
        return forge_text

    pattern = r"(\* @param UiScale\s*\n(?:\s*\*[^\n]*\n)*?\s*\* @default )auto"
    if scale != "auto":
        forge_text, n = re.subn(pattern, rf"\g<1>{scale}", forge_text, count=1)
        if n == 0:
            raise ValueError("Could not patch @default UiScale in Forge_MV.js")
    return forge_text


def _patch_forge_mtc_defaults(forge_text: str, hotkey: str, ui_scale: str) -> str:
    hk = json.dumps(hotkey.strip() or "F10")
    scale = json.dumps(str(ui_scale or "auto").strip() or "auto")
    forge_text = re.sub(r"_hotkey: 'F10'", f"_hotkey: {hk}", forge_text, count=1)
    forge_text = re.sub(r"_uiScale: 'auto'", f"_uiScale: {scale}", forge_text, count=1)
    return forge_text


def _patch_forge_runtime(forge_text: str, hotkey: str, ui_scale: str, engine: str) -> str:
    hk = json.dumps(hotkey.strip() or "F10")
    scale = json.dumps(str(ui_scale or "auto").strip() or "auto")
    if engine == "MZ":
        forge_text = re.sub(
            r"window\.Forge\._hotkey = \(P\.hotkey \|\| '[^']*'\)\.trim\(\);",
            f"window.Forge._hotkey = {hk};",
            forge_text,
            count=1,
        )
        forge_text = re.sub(
            r"window\.Forge\._uiScale = \(P\.uiScale \|\| '[^']*'\)\.trim\(\);",
            f"window.Forge._uiScale = {scale};",
            forge_text,
            count=1,
        )
        return forge_text

    forge_text = re.sub(
        r"window\.Forge\._hotkey = \(P\.Hotkey \|\| '[^']*'\)\.trim\(\);",
        f"window.Forge._hotkey = {hk};",
        forge_text,
        count=1,
    )
    forge_text = re.sub(
        r"window\.Forge\._uiScale = \(P\.UiScale \|\| '[^']*'\)\.trim\(\);",
        f"window.Forge._uiScale = {scale};",
        forge_text,
        count=1,
    )
    return forge_text


def _remove_legacy_launcher(forge_text: str) -> str:
    """Keep legacy Forge shortcut-only by leaving its launcher detached."""
    marker = "    rootEl.appendChild(launcher);"
    if forge_text.count(marker) != 1:
        raise ValueError("Could not disable legacy Forge launcher")
    return forge_text.replace(
        marker,
        "    // Floating launcher disabled; use the configured Forge shortcut.",
        1,
    )


def is_legacy_forge_plugin(text: str) -> bool:
    """True for pre-rewrite Forge_MV/MZ plugins with RPG Maker @param blocks."""
    return "@param Hotkey" in text or "@param hotkey" in text


def prepare_forge_js(engine: str, source: Path | None = None, cfg: dict | None = None) -> str:
    """Build the Forge plugin written into a game folder (vanilla source + Dazed patches)."""
    src = source or bundled_plugin_path(engine)
    text = src.read_text(encoding="utf-8")
    effective = {**load_config(), **(cfg or {})}
    hotkey = effective.get("forgeHotkey", "F10")
    ui_scale = effective.get("uiScale", "auto")

    if not is_legacy_forge_plugin(text):
        return apply_modern_forge_patches(text, hotkey, str(ui_scale))

    text = apply_ui_scale_patches(text, engine)
    text = _patch_forge_hotkey(text, hotkey, engine)
    text = _patch_forge_ui_scale_default(text, str(ui_scale), engine)
    text = _patch_forge_mtc_defaults(text, hotkey, str(ui_scale))
    text = _patch_forge_runtime(text, hotkey, str(ui_scale), engine)
    text = _remove_legacy_launcher(text)
    return text


# Back-compat alias
def prepare_forge_mz_js(source: Path | None = None, cfg: dict | None = None) -> str:
    return prepare_forge_js("MZ", source, cfg)
