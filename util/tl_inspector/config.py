"""TL Inspector configuration — .env storage, editor detection, JS patching."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from dotenv import dotenv_values

ENV_EDITOR = "tlEditorCmd"

CFG_KEYS = ("editorCmd", "workspaceFolder")

DEFAULTS = {
    "editorCmd": "auto",
    "workspaceFolder": "auto",
}

_PKG_ROOT = Path(__file__).resolve().parent
BUNDLED_PLUGIN = _PKG_ROOT / "TLInspector.js"
ENV_PATH = Path(".env")


def detect_editors() -> list[tuple[str, Path]]:
    """Return installed code editors as (label, executable path) pairs."""
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add(label: str, path: Path) -> None:
        key = str(path).lower()
        if key in seen or not path.is_file():
            return
        seen.add(key)
        out.append((label, path))

    if sys.platform == "win32":
        bases = [
            os.environ.get("LOCALAPPDATA"),
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
        ]
        for raw in bases:
            if not raw:
                continue
            base = Path(raw)
            add("VS Code", base / "Programs" / "Microsoft VS Code" / "Code.exe")
            add("VS Code", base / "Microsoft VS Code" / "Code.exe")
            add(
                "VS Code Insiders",
                base / "Programs" / "Microsoft VS Code Insiders" / "Code - Insiders.exe",
            )
            add("Cursor", base / "Programs" / "cursor" / "Cursor.exe")
            add("Cursor", base / "cursor" / "Cursor.exe")
    elif sys.platform == "darwin":
        add(
            "VS Code",
            Path("/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"),
        )
        add("Cursor", Path("/Applications/Cursor.app/Contents/MacOS/Cursor"))
    else:
        for path in (
            Path("/usr/bin/code"),
            Path("/usr/share/code/bin/code"),
            Path("/snap/bin/code"),
            Path("/usr/bin/cursor"),
        ):
            label = "Cursor" if "cursor" in path.name else "VS Code"
            add(label, path)

    return out


def detect_primary_editor() -> Path | None:
    editors = detect_editors()
    return editors[0][1] if editors else None


def load_config(env_path: Path | None = None) -> dict:
    path = env_path or ENV_PATH
    env = dotenv_values(path) if path.is_file() else {}
    cfg = dict(DEFAULTS)
    editor = (env.get(ENV_EDITOR) or "").strip()
    if editor:
        cfg["editorCmd"] = editor
    return cfg


def save_config(cfg: dict, env_path: Path | None = None) -> None:
    path = env_path or ENV_PATH
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    updates = {
        ENV_EDITOR: cfg.get("editorCmd", "auto"),
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


def _js_literal(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def patch_cfg_block(js: str, overrides: dict) -> str:
    for key, val in overrides.items():
        if key not in CFG_KEYS:
            continue
        lit = _js_literal(val)
        pattern = rf"({re.escape(key)}:\s*)(?:'[^']*'|\"[^\"]*\"|true|false|null|\d+)"
        js, count = re.subn(pattern, rf"\g<1>{lit}", js, count=1)
        if count == 0:
            raise ValueError(f"Could not patch CFG.{key} in TLInspector.js")
    return js


def prepare_plugin_js(source: Path | None = None, cfg: dict | None = None) -> str:
    src = source or BUNDLED_PLUGIN
    text = src.read_text(encoding="utf-8")
    effective = {**DEFAULTS, **(cfg or load_config())}
    effective["workspaceFolder"] = "auto"
    return patch_cfg_block(text, effective)
