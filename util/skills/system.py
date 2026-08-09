"""Load the static system prompt and optional per-game skill overlays."""

from __future__ import annotations

import os
import re
from pathlib import Path

from util.paths import (
    GAME_QUIRKS_RELATIVE,
    GAME_SKILL_RELATIVE,
    GAME_SKILL_RESERVED_NAMES,
    GAME_SKILLS_RELATIVE,
    GameProjectPathError,
    LEGACY_GAME_SKILL_RELATIVE,
    LEGACY_GAME_SKILLS_RELATIVE,
    LEGACY_QUIRKS_FILENAME,
    PROMPT_PATH,
    ensure_game_tool_gitignore,
    game_metadata_dir,
    prepare_game_translation_context,
)

_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# Drop legacy IDE-only sections from older game skill files.
_IDE_SECTION_RE = re.compile(
    r"\n## (?:Voice rules|Tool boundaries)\b.*?(?=\n## |\Z)",
    re.DOTALL | re.IGNORECASE,
)


def quirks_path_for_game(game_root: str | Path | None) -> Path | None:
    """Return ``<game_root>/.dazedtl/skills/quirks.md`` when available.

    Also migrates a legacy ``translation_quirks.txt`` in the game root if present.
    """
    if not game_root:
        return None
    root = Path(game_root).expanduser().resolve()
    skills = game_skills_dir(root)
    if skills is None:
        return None
    preferred = root / GAME_QUIRKS_RELATIVE
    legacy = root / LEGACY_QUIRKS_FILENAME
    preferred_present = preferred.exists() or preferred.is_symlink()
    legacy_present = legacy.exists() or legacy.is_symlink()
    if preferred_present and (preferred.is_symlink() or not preferred.is_file()):
        raise GameProjectPathError(
            f"Portable quirks path is not a regular file: {preferred}"
        )
    if legacy_present and (legacy.is_symlink() or not legacy.is_file()):
        raise GameProjectPathError(
            f"Legacy quirks path is not a regular file: {legacy}"
        )
    if preferred_present and legacy_present:
        raise GameProjectPathError(
            "Both the legacy and portable quirks files exist. DazedTL did not "
            f"overwrite either file:\n- {legacy}\n- {preferred}"
        )
    if legacy_present:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        try:
            legacy.rename(preferred)
        except OSError as exc:
            raise GameProjectPathError(
                f"Could not move {legacy} to {preferred}: {exc}"
            ) from exc
    return preferred


def game_skill_path_for_game(game_root: str | Path | None) -> Path | None:
    """Return ``<game_root>/.dazedtl/skills/game.md`` when available.

    Migrates legacy ``skills/translation.md`` to ``game.md`` when needed.
    """
    if not game_root:
        return None
    root = Path(game_root).expanduser().resolve()
    skills = game_skills_dir(root)
    if skills is None:
        return None
    preferred = root / GAME_SKILL_RELATIVE
    legacy = root / LEGACY_GAME_SKILL_RELATIVE
    preferred_present = preferred.exists() or preferred.is_symlink()
    legacy_present = legacy.exists() or legacy.is_symlink()
    if preferred_present and (preferred.is_symlink() or not preferred.is_file()):
        raise GameProjectPathError(
            f"Portable game skill path is not a regular file: {preferred}"
        )
    if legacy_present and (legacy.is_symlink() or not legacy.is_file()):
        raise GameProjectPathError(
            f"Legacy game skill path is not a regular file: {legacy}"
        )
    if preferred_present and legacy_present:
        raise GameProjectPathError(
            "Both the legacy and portable game skill files exist. DazedTL did "
            f"not overwrite either file:\n- {legacy}\n- {preferred}"
        )
    if legacy_present:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        try:
            legacy.rename(preferred)
        except OSError as exc:
            raise GameProjectPathError(
                f"Could not move {legacy} to {preferred}: {exc}"
            ) from exc
    return preferred


def migrate_game_skill_text(text: str) -> str:
    """Normalize a game skill body for API use (path fixes + drop IDE scaffolding)."""
    if not text:
        return text
    # Common stale pointers from older Project Setup output.
    updated = text.replace("translation_quirks.txt", ".dazedtl/skills/quirks.md")
    updated = updated.replace(
        "`translation_quirks.md`", "`.dazedtl/skills/quirks.md`"
    )
    updated = re.sub(
        r"(?<!skills/)(?<![\w./-])quirks\.md(?![\w.-])",
        ".dazedtl/skills/quirks.md",
        updated,
    )
    updated = updated.replace("skills/skills/quirks.md", ".dazedtl/skills/quirks.md")
    updated = re.sub(
        r"(?<!\.dazedtl/)skills/quirks\.md",
        ".dazedtl/skills/quirks.md",
        updated,
    )
    # Older templates included IDE-only Voice rules / Tool boundaries sections.
    updated = _IDE_SECTION_RE.sub("\n", updated)
    updated = re.sub(r"\n{3,}", "\n\n", updated).strip() + "\n"
    return updated


def game_skills_dir(game_root: str | Path | None) -> Path | None:
    """Return the portable skills directory, migrating the former root folder."""
    if not game_root:
        return None
    root = Path(game_root).expanduser().resolve()
    if not root.is_dir():
        return root / GAME_SKILLS_RELATIVE
    validate_game_skills_migration(root)
    metadata = game_metadata_dir(root)
    preferred = root / GAME_SKILLS_RELATIVE
    legacy = root / LEGACY_GAME_SKILLS_RELATIVE
    legacy_present = legacy.exists() or legacy.is_symlink()
    ensure_game_tool_gitignore(root)
    if legacy_present:
        metadata.mkdir(exist_ok=True)
        try:
            legacy.rename(preferred)
        except OSError as exc:
            raise GameProjectPathError(
                f"Could not move {legacy} to {preferred}: {exc}"
            ) from exc
    return preferred


def validate_game_skills_migration(game_root: str | Path | None) -> None:
    """Validate all legacy skill moves without changing the selected game."""
    if not game_root or not str(game_root).strip():
        return
    root = Path(game_root).expanduser().resolve()
    if not root.is_dir():
        return

    game_metadata_dir(root)
    preferred = root / GAME_SKILLS_RELATIVE
    legacy = root / LEGACY_GAME_SKILLS_RELATIVE
    preferred_present = preferred.exists() or preferred.is_symlink()
    legacy_present = legacy.exists() or legacy.is_symlink()
    if preferred_present and (preferred.is_symlink() or not preferred.is_dir()):
        raise GameProjectPathError(
            f"Portable skills path is not a normal folder: {preferred}"
        )
    if legacy_present and (legacy.is_symlink() or not legacy.is_dir()):
        raise GameProjectPathError(
            f"Legacy skills path is not a normal folder: {legacy}"
        )
    if legacy_present:
        unsupported = [
            path.name
            for path in legacy.iterdir()
            if path.is_symlink()
            or not path.is_file()
            or path.suffix.casefold() != ".md"
        ]
        if unsupported:
            raise GameProjectPathError(
                "The legacy skills folder contains entries DazedTL cannot move "
                "automatically: " + ", ".join(sorted(unsupported))
            )
    if preferred_present and legacy_present:
        raise GameProjectPathError(
            "Both the legacy and portable skills folders exist. DazedTL did not "
            f"merge or overwrite them:\n- {legacy}\n- {preferred}"
        )

    effective = legacy if legacy_present else preferred
    quirks = effective / "quirks.md"
    root_quirks = root / LEGACY_QUIRKS_FILENAME
    game_skill = effective / "game.md"
    translation_skill = effective / "translation.md"
    for path, label in (
        (quirks, "Quirks"),
        (root_quirks, "Legacy quirks"),
        (game_skill, "Game skill"),
        (translation_skill, "Legacy game skill"),
    ):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise GameProjectPathError(f"{label} path is not a regular file: {path}")
    if quirks.exists() and root_quirks.exists():
        raise GameProjectPathError(
            "Both the legacy and portable quirks files exist. DazedTL did not "
            f"overwrite either file:\n- {root_quirks}\n- {quirks}"
        )
    if game_skill.exists() and translation_skill.exists():
        raise GameProjectPathError(
            "Both the legacy and portable game skill files exist. DazedTL did "
            f"not overwrite either file:\n- {translation_skill}\n- {game_skill}"
        )

    if effective.is_dir():
        for path in effective.glob("*.md"):
            if path.is_symlink() or not path.is_file():
                raise GameProjectPathError(
                    f"Portable skill path is not a regular file: {path}"
                )


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
    """Return ``<game_root>/.dazedtl/skills/<name>.md`` for a valid name."""
    stem = sanitize_custom_skill_stem(name)
    skills = game_skills_dir(game_root)
    if not stem or skills is None:
        return None
    path = skills / f"{stem}.md"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise GameProjectPathError(
            f"Portable custom skill path is not a regular file: {path}"
        )
    return path


def list_custom_skill_paths(game_root: str | Path | None) -> list[Path]:
    """List custom skill Markdown under ``<game>/.dazedtl/skills/``.

    Excludes built-in ``quirks.md`` and ``game.md`` (and legacy ``translation.md``).
    """
    skills = game_skills_dir(game_root)
    if skills is None or not skills.is_dir():
        return []
    reserved = {n.lower() for n in GAME_SKILL_RESERVED_NAMES}
    out: list[Path] = []
    for path in sorted(skills.glob("*.md"), key=lambda p: p.name.lower()):
        if path.name.lower() in reserved:
            continue
        if path.is_symlink() or not path.is_file():
            raise GameProjectPathError(
                f"Portable custom skill path is not a regular file: {path}"
            )
        out.append(path)
    return out


def load_system_prompt(game_root: str | Path | None = None) -> str:
    """Load ``data/skills/system.md`` plus optional per-game overlays.

    Overlay order (when ``DAZED_GAME_ROOT`` / *game_root* is set):
      1. ``.dazedtl/skills/game.md`` - Translation Frame / game skill (API)
      2. ``.dazedtl/skills/quirks.md`` - cross-cutting voice quirks
      3. other ``.dazedtl/skills/*.md`` - optional custom overlays

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

    # Prepare once at this shared boundary so Evaluation, direct module use,
    # and GUI translation all see the same complete portable context.
    prepare_game_translation_context(root)

    parts = [base.rstrip()] if base.strip() else []

    skill_file = game_skill_path_for_game(root)
    if skill_file and skill_file.is_file():
        skill = migrate_game_skill_text(skill_file.read_text(encoding="utf-8")).strip()
        if skill:
            parts.append("## Game Translation Frame\n\n" + skill)

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
