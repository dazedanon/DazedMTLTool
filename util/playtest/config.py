"""Shared playtest plugin settings — hotkeys and editor (.env)."""

from __future__ import annotations

import re
from pathlib import Path

from dotenv import dotenv_values

ENV_TL_HOTKEY = "tlHotkey"
ENV_FORGE_HOTKEY = "forgeHotkey"
ENV_UI_SCALE = "playtestUiScale"
ENV_EDITOR = "tlEditorCmd"

DEFAULTS = {
    "hotkey": "F9",
    "forgeHotkey": "F10",
    "uiScale": "auto",
    "editorCmd": "auto",
    "workspaceFolder": "auto",
}

ENV_PATH = Path(".env")


def load_config(env_path: Path | None = None) -> dict:
    path = env_path or ENV_PATH
    env = dotenv_values(path) if path.is_file() else {}
    cfg = dict(DEFAULTS)
    for key, env_key in (
        ("hotkey", ENV_TL_HOTKEY),
        ("forgeHotkey", ENV_FORGE_HOTKEY),
        ("uiScale", ENV_UI_SCALE),
        ("editorCmd", ENV_EDITOR),
    ):
        val = (env.get(env_key) or "").strip()
        if val:
            cfg[key] = val
    return cfg


def save_config(cfg: dict, env_path: Path | None = None) -> None:
    path = env_path or ENV_PATH
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    updates = {
        ENV_TL_HOTKEY: cfg.get("hotkey", DEFAULTS["hotkey"]),
        ENV_FORGE_HOTKEY: cfg.get("forgeHotkey", DEFAULTS["forgeHotkey"]),
        ENV_UI_SCALE: cfg.get("uiScale", DEFAULTS["uiScale"]),
        ENV_EDITOR: cfg.get("editorCmd", DEFAULTS["editorCmd"]),
    }
    for key, val in updates.items():
        quoted = f"'{val}'"
        pattern = rf"^({re.escape(key)}\s*=\s*)(?:'[^']*'|\"[^\"]*\"|[^\n]*)"
        text, n = re.subn(pattern, rf"\g<1>{quoted}", text, count=1, flags=re.MULTILINE)
        if n == 0:
            text = text.rstrip("\n") + f"\n{key}={quoted}\n"
    if not path.exists():
        path.touch()
    path.write_text(text, encoding="utf-8")
