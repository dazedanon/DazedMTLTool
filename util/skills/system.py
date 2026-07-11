"""Load the static system prompt and optional per-game quirks overlay."""

from __future__ import annotations

import os
import re
from pathlib import Path

from util.paths import (
    GAME_QUIRKS_RELATIVE,
    GAME_SKILL_RELATIVE,
    GAME_SKILL_RESERVED_NAMES,
    LEGACY_QUIRKS_FILENAME,
    PROMPT_PATH,
)

_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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


def migrate_game_skill_text(text: str) -> str:
    """Rewrite legacy quirk path names inside a game skill markdown body."""
    if not text:
        return text
    # Common stale pointers from older Project Setup output.
    updated = text.replace("translation_quirks.txt", "skills/quirks.md")
    updated = updated.replace("`translation_quirks.md`", "`skills/quirks.md`")
    # Bare relative quirks.md without skills/ prefix (keep skills/quirks.md intact).
    updated = re.sub(
        r"(?<!skills/)(?<![\w./-])quirks\.md(?![\w.-])",
        "skills/quirks.md",
        updated,
    )
    # Avoid double skills/skills/
    updated = updated.replace("skills/skills/quirks.md", "skills/quirks.md")
    return updated


def game_skills_dir(game_root: str | Path | None) -> Path | None:
    """Return ``<game_root>/skills`` when *game_root* is set."""
    if not game_root:
        return None
    return Path(game_root) / "skills"


def sanitize_custom_skill_stem(name: str) -> str | None:
    """Return a safe skill stem (no ``.md``) or None if invalid/reserved."""
    raw = (name or "").strip()
    if not raw:
        return None
    if raw.lower().endswith(".md"):
        raw = raw[:-3].strip()
    if not _SKILL_NAME_RE.match(raw):
        return None
    filename = f"{raw}.md"
    if filename.lower() in {n.lower() for n in GAME_SKILL_RESERVED_NAMES}:
        return None
    return raw


def custom_skill_path_for_game(
    game_root: str | Path | None, name: str
) -> Path | None:
    """Return ``<game_root>/skills/<name>.md`` for a valid custom skill name."""
    stem = sanitize_custom_skill_stem(name)
    skills = game_skills_dir(game_root)
    if not stem or skills is None:
        return None
    return skills / f"{stem}.md"


def list_custom_skill_paths(game_root: str | Path | None) -> list[Path]:
    """List user custom skill markdown files under ``<game>/skills/``.

    Excludes built-in ``quirks.md`` and ``translation.md``.
    """
    skills = game_skills_dir(game_root)
    if skills is None or not skills.is_dir():
        return []
    reserved = {n.lower() for n in GAME_SKILL_RESERVED_NAMES}
    out: list[Path] = []
    for path in sorted(skills.glob("*.md"), key=lambda p: p.name.lower()):
        if path.name.lower() in reserved:
            continue
        if path.is_file():
            out.append(path)
    return out


def load_system_prompt(game_root: str | Path | None = None) -> str:
    """Load ``data/skills/system.md`` plus optional per-game overlays.

    Overlay order:
      1. ``skills/quirks.md`` (voice quirks)
      2. Any other ``skills/*.md`` except ``translation.md`` (custom skills)

    Path resolution order for the game root:
      1. Explicit *game_root* argument
      2. ``DAZED_GAME_ROOT`` environment variable
    """
    base = ""
    if PROMPT_PATH.is_file():
        base = PROMPT_PATH.read_text(encoding="utf-8")

    root = game_root or os.getenv("DAZED_GAME_ROOT") or ""
    root = str(root).strip()
    if not root:
        return base

    parts = [base.rstrip()] if base.strip() else []

    quirks_file = quirks_path_for_game(root)
    if quirks_file and quirks_file.is_file():
        quirks = quirks_file.read_text(encoding="utf-8").strip()
        if quirks:
            parts.append("## Game-Specific Translation Quirks\n\n" + quirks)

    for path in list_custom_skill_paths(root):
        body = path.read_text(encoding="utf-8").strip()
        if not body:
            continue
        title = path.stem.replace("_", " ").replace("-", " ").strip() or path.stem
        parts.append(f"## Custom Game Skill: {title}\n\n{body}")

    if not parts:
        return base
    return "\n\n".join(parts) + "\n"
