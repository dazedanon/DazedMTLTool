"""Load the static system prompt and optional per-game quirks overlay."""

from __future__ import annotations

import os
from pathlib import Path

from util.paths import (
    GAME_QUIRKS_RELATIVE,
    GAME_SKILL_RELATIVE,
    LEGACY_QUIRKS_FILENAME,
    PROMPT_PATH,
)


def quirks_path_for_game(game_root: str | Path | None) -> Path | None:
    """Return ``<game_root>/skills/quirks.md`` when *game_root* is set.

    Also migrates a legacy ``translation_quirks.txt`` in the game root if present.
    """
    if not game_root:
        return None
    root = Path(game_root)
    preferred = root / GAME_QUIRKS_RELATIVE
    legacy = root / LEGACY_QUIRKS_FILENAME
    if not preferred.is_file() and legacy.is_file():
        preferred.parent.mkdir(parents=True, exist_ok=True)
        try:
            legacy.rename(preferred)
        except OSError:
            # Fall back to reading the legacy path if rename fails.
            return legacy
    return preferred


def game_skill_path_for_game(game_root: str | Path | None) -> Path | None:
    """Return ``<game_root>/skills/translation.md`` when *game_root* is set."""
    if not game_root:
        return None
    return Path(game_root) / GAME_SKILL_RELATIVE


def load_system_prompt(game_root: str | Path | None = None) -> str:
    """Load ``data/skills/system.md`` and optionally append per-game quirks.

    Quirks path resolution order:
      1. Explicit *game_root* argument
      2. ``DAZED_GAME_ROOT`` environment variable
    """
    base = ""
    if PROMPT_PATH.is_file():
        base = PROMPT_PATH.read_text(encoding="utf-8")

    root = game_root or os.getenv("DAZED_GAME_ROOT") or ""
    root = str(root).strip()
    quirks_file = quirks_path_for_game(root) if root else None
    if quirks_file and quirks_file.is_file():
        quirks = quirks_file.read_text(encoding="utf-8").strip()
        if quirks:
            return (
                base.rstrip()
                + "\n\n## Game-Specific Translation Quirks\n\n"
                + quirks
                + "\n"
            )
    return base
