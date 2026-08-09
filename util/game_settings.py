"""Per-game DazedTL workflow settings stored with the selected game."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path


GAME_SETTINGS_RELATIVE = Path(".dazedtl") / "settings.json"
WRAP_WIDTH_KEYS = ("width", "faceWidth", "listWidth", "noteWidth")
DEFAULT_WRAP_WIDTHS = {
    "width": 60,
    "faceWidth": 50,
    "listWidth": 100,
    "noteWidth": 75,
}
MIN_WRAP_WIDTH = 20
MAX_WRAP_WIDTH = 300


class GameSettingsError(ValueError):
    """Raised when an existing per-game settings file cannot be used safely."""


def game_settings_path(game_root: str | Path) -> Path:
    """Return ``<game>/.dazedtl/settings.json`` for a selected game root."""
    return Path(game_root).expanduser().resolve() / GAME_SETTINGS_RELATIVE


def _coerce_width(value, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        width = int(value)
    except (TypeError, ValueError):
        return fallback
    if not MIN_WRAP_WIDTH <= width <= MAX_WRAP_WIDTH:
        return fallback
    return width


def normalize_wrap_widths(
    values: Mapping | None,
    *,
    defaults: Mapping | None = None,
) -> dict[str, int]:
    """Return complete bounded wrap widths, clamping face width to dialogue."""
    fallback = dict(DEFAULT_WRAP_WIDTHS)
    if defaults:
        for key in WRAP_WIDTH_KEYS:
            fallback[key] = _coerce_width(defaults.get(key), fallback[key])

    source = values if isinstance(values, Mapping) else {}
    normalized = {
        key: _coerce_width(source.get(key), fallback[key])
        for key in WRAP_WIDTH_KEYS
    }
    normalized["faceWidth"] = min(normalized["width"], normalized["faceWidth"])
    return normalized


def _read_settings(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GameSettingsError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GameSettingsError(f"Expected a JSON object in {path}")
    return data


def load_game_wrap_widths(game_root: str | Path) -> dict[str, int] | None:
    """Load saved wrap widths, or return ``None`` when the game has none yet."""
    path = game_settings_path(game_root)
    if not path.is_file():
        return None
    data = _read_settings(path)
    rpgmaker = data.get("rpgmaker")
    if not isinstance(rpgmaker, dict):
        raise GameSettingsError(f"Missing rpgmaker settings object in {path}")
    widths = rpgmaker.get("wrapWidths")
    if not isinstance(widths, dict):
        raise GameSettingsError(f"Missing rpgmaker.wrapWidths object in {path}")
    return normalize_wrap_widths(widths)


def save_game_wrap_widths(
    game_root: str | Path,
    values: Mapping,
) -> Path:
    """Atomically save wrap widths while preserving unrelated game settings."""
    root = Path(game_root).expanduser().resolve()
    if not root.is_dir():
        raise GameSettingsError(f"Game folder does not exist: {root}")

    path = game_settings_path(root)
    data = _read_settings(path) if path.is_file() else {}
    normalized = normalize_wrap_widths(values)

    rpgmaker = data.get("rpgmaker")
    if rpgmaker is None:
        rpgmaker = {}
        data["rpgmaker"] = rpgmaker
    elif not isinstance(rpgmaker, dict):
        raise GameSettingsError(f"Expected rpgmaker to be an object in {path}")

    data["version"] = 1
    rpgmaker["wrapWidths"] = normalized
    path.parent.mkdir(exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".settings-",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path
