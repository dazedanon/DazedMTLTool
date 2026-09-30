"""Canonical project paths (repo root, data files, config)."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

# Product identity (QSettings / desktop / window titles).
ORG_NAME = "DazedTranslations"
APP_NAME = "DazedTL"
LEGACY_APP_NAME = "DazedMTLTool"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
GLOSSARY_FILENAME = "glossary.txt"
GLOSSARY_OVERRIDE_ENV = "DAZED_GLOSSARY_PATH"
GLOSSARY_BASE_ENABLED_ENV = "DAZED_INCLUDE_GLOSSARY_BASE"
GAME_METADATA_RELATIVE = Path(".dazedtl")
GAME_GLOSSARY_RELATIVE = GAME_METADATA_RELATIVE / GLOSSARY_FILENAME
LEGACY_GAME_GLOSSARY_RELATIVE = Path(GLOSSARY_FILENAME)
GLOSSARY_BASE_PATH = DATA_DIR / "glossary_base.txt"
SKILLS_DIR = DATA_DIR / "skills"
HELP_DIR = DATA_DIR / "help"
# Runtime translation system skill (formerly data/prompt.txt).
PROMPT_PATH = SKILLS_DIR / "system.md"
LEGACY_PROMPT_PATH = DATA_DIR / "prompt.txt"
LAST_UPDATE_SHA_PATH = DATA_DIR / "last_update_sha.txt"
ENV_PATH = PROJECT_ROOT / ".env"
ICON_PATH = PROJECT_ROOT / "assets" / "icon.png"
TRANSLATION_CONTEXTS_PATH = DATA_DIR / "translation_contexts.json"
SFX_REFERENCE_PATH = DATA_DIR / "sfx_reference" / "j_ono.json"
# Per-game API overlays. Root-level skills/ from older versions are migrated.
GAME_SKILLS_RELATIVE = GAME_METADATA_RELATIVE / "skills"
LEGACY_GAME_SKILLS_RELATIVE = Path("skills")
GAME_QUIRKS_RELATIVE = GAME_SKILLS_RELATIVE / "quirks.md"
LEGACY_QUIRKS_FILENAME = "translation_quirks.txt"
GAME_SKILL_RELATIVE = GAME_SKILLS_RELATIVE / "game.md"
LEGACY_GAME_SKILL_RELATIVE = GAME_SKILLS_RELATIVE / "translation.md"
# Built-in skill filenames under <game>/.dazedtl/skills/ (not custom overlays).
GAME_SKILL_RESERVED_NAMES = frozenset({"quirks.md", "game.md", "translation.md"})

GAME_TOOL_GITIGNORE_BEGIN = "# BEGIN DazedTL portable translation settings"
GAME_TOOL_GITIGNORE_END = "# END DazedTL portable translation settings"
GAME_IMAGE_PATCH_GITIGNORE_COMMENT = "# DazedTL selected image patches"
LEGACY_GAME_TOOL_GITIGNORE_COMMENT = "# DazedTL image manager working files"
LEGACY_GAME_TOOL_GITIGNORE_RULE = "/.dazedtl/"
GAME_TOOL_GITIGNORE_BLOCK = "\n".join(
    (
        GAME_TOOL_GITIGNORE_BEGIN,
        "!/.dazedtl/",
        "/.dazedtl/*",
        "!/.dazedtl/glossary.txt",
        "!/.dazedtl/settings.json",
        "!/.dazedtl/skills/",
        "/.dazedtl/skills/*",
        "!/.dazedtl/skills/*.md",
        GAME_TOOL_GITIGNORE_END,
    )
) + "\n"

_ROOT_DATA_FILES = (
    "prompt.txt",
    "last_update_sha.txt",
)

GLOSSARY_BASE_SEPARATOR = (
    "# ── Base Glossary (auto-appended from glossary_base.txt — do not edit below) ──\n"
)
_EMPTY_GLOSSARY_PLACEHOLDER = "# Add character glossary entries here\n"


class GameProjectPathError(RuntimeError):
    """Raised when portable game files cannot be migrated without data loss."""


def migrate_root_data_files() -> None:
    """Move legacy root-level data files into data/ on first run."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in _ROOT_DATA_FILES:
        src = PROJECT_ROOT / name
        dst = DATA_DIR / name
        if src.is_file() and not dst.exists():
            src.rename(dst)


def migrate_prompt_to_skills() -> None:
    """Move legacy ``data/prompt.txt`` to ``data/skills/system.md`` when needed."""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    if PROMPT_PATH.is_file():
        return
    for legacy in (LEGACY_PROMPT_PATH, PROJECT_ROOT / "prompt.txt"):
        if legacy.is_file():
            legacy.rename(PROMPT_PATH)
            return


def migrate_app_settings() -> None:
    """Copy QSettings from the legacy app name into DazedTL once."""
    try:
        from PyQt5.QtCore import QSettings
    except ImportError:
        return

    new = QSettings(ORG_NAME, APP_NAME)
    if str(new.value("_migrated_from_legacy_app", "")) == "1":
        return

    old = QSettings(ORG_NAME, LEGACY_APP_NAME)
    old_keys = list(old.allKeys())
    new_keys = [k for k in new.allKeys() if k != "_migrated_from_legacy_app"]
    if old_keys and not new_keys:
        for key in old_keys:
            new.setValue(key, old.value(key))
    new.setValue("_migrated_from_legacy_app", "1")


def normalize_game_tool_gitignore_text(
    existing: str,
    *,
    path_label: str = ".gitignore",
) -> str:
    """Return content with one canonical managed block in its existing position."""
    pieces: list[str] = []
    first_block_piece: int | None = None
    cursor = 0
    while True:
        start = existing.find(GAME_TOOL_GITIGNORE_BEGIN, cursor)
        stray_end = existing.find(GAME_TOOL_GITIGNORE_END, cursor)
        if start < 0:
            if stray_end >= 0:
                raise GameProjectPathError(
                    f"DazedTL's managed .gitignore block is incomplete in {path_label}"
                )
            pieces.append(existing[cursor:])
            break
        if 0 <= stray_end < start:
            raise GameProjectPathError(
                f"DazedTL's managed .gitignore block is incomplete in {path_label}"
            )
        end = existing.find(GAME_TOOL_GITIGNORE_END, start)
        if end < 0:
            raise GameProjectPathError(
                f"DazedTL's managed .gitignore block is incomplete in {path_label}"
            )
        nested_start = existing.find(
            GAME_TOOL_GITIGNORE_BEGIN,
            start + len(GAME_TOOL_GITIGNORE_BEGIN),
        )
        if 0 <= nested_start < end:
            raise GameProjectPathError(
                f"DazedTL's managed .gitignore block is incomplete in {path_label}"
            )
        pieces.append(existing[cursor:start])
        if first_block_piece is None:
            first_block_piece = len(pieces)
        cursor = end + len(GAME_TOOL_GITIGNORE_END)
        if cursor < len(existing) and existing[cursor] == "\r":
            cursor += 1
        if cursor < len(existing) and existing[cursor] == "\n":
            cursor += 1

    def without_legacy_rules(value: str) -> str:
        lines = value.splitlines(keepends=True)
        cleaned_lines: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            rule = line.rstrip("\r\n")
            next_rule = (
                lines[index + 1].rstrip("\r\n")
                if index + 1 < len(lines)
                else None
            )
            if (
                rule == LEGACY_GAME_TOOL_GITIGNORE_COMMENT
                and next_rule == LEGACY_GAME_TOOL_GITIGNORE_RULE
            ):
                index += 2
                continue
            if rule == LEGACY_GAME_TOOL_GITIGNORE_RULE:
                index += 1
                continue
            cleaned_lines.append(line)
            index += 1
        return "".join(cleaned_lines)

    if first_block_piece is not None:
        before = without_legacy_rules("".join(pieces[:first_block_piece])).rstrip(
            "\r\n"
        )
        after = without_legacy_rules("".join(pieces[first_block_piece:])).strip(
            "\r\n"
        )
        normalized = f"{before}\n\n" if before else ""
        normalized += GAME_TOOL_GITIGNORE_BLOCK
        if after:
            normalized += f"\n{after}\n"
        return normalized

    prefix = without_legacy_rules("".join(pieces)).rstrip("\r\n")
    image_section = ""
    image_start = prefix.find(GAME_IMAGE_PATCH_GITIGNORE_COMMENT)
    if image_start >= 0:
        image_section = prefix[image_start:].strip("\r\n")
        prefix = prefix[:image_start].rstrip("\r\n")
    if prefix:
        prefix += "\n\n"
    normalized = prefix + GAME_TOOL_GITIGNORE_BLOCK
    if image_section:
        normalized += "\n" + image_section + "\n"
    return normalized


def ensure_game_tool_gitignore(game_root: str | Path) -> bool:
    """Allowlist portable translation settings while ignoring other tool state.

    The managed block replaces older ``/.dazedtl/`` rules. Its existing position
    is retained to avoid meaningless Git churn; only portable glossary/settings/
    skills are exposed.
    """
    root = Path(game_root).expanduser().resolve()
    if not root.is_dir():
        raise GameProjectPathError(f"Game folder does not exist: {root}")
    path = root / ".gitignore"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise GameProjectPathError(f"Game .gitignore is not a regular file: {path}")
    try:
        existing = (
            path.read_text(encoding="utf-8", errors="surrogateescape")
            if path.is_file()
            else ""
        )
    except OSError as exc:
        raise GameProjectPathError(f"Could not read {path}: {exc}") from exc

    updated = normalize_game_tool_gitignore_text(existing, path_label=str(path))
    if updated == existing:
        return False

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".gitignore.dazedtl-", dir=root
    )
    temporary = Path(temporary_name)
    original_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    try:
        with os.fdopen(
            descriptor, "w", encoding="utf-8", errors="surrogateescape"
        ) as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, original_mode)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return True


def game_metadata_dir(game_root: str | Path, *, create: bool = False) -> Path:
    """Return a normal ``.dazedtl`` directory without following a directory link."""
    root = Path(game_root).expanduser().resolve()
    if not root.is_dir():
        raise GameProjectPathError(f"Game folder does not exist: {root}")
    metadata = root / GAME_METADATA_RELATIVE
    if metadata.is_symlink() or (metadata.exists() and not metadata.is_dir()):
        raise GameProjectPathError(
            f"DazedTL metadata path is not a normal folder: {metadata}"
        )
    if create:
        metadata.mkdir(exist_ok=True)
    return metadata


migrate_root_data_files()
migrate_prompt_to_skills()


def glossary_base_path() -> Path:
    """Return the shipped base glossary."""
    return GLOSSARY_BASE_PATH


def _game_glossary_paths(
    game_root: str | Path | None,
) -> tuple[Path, Path, Path] | None:
    """Return the root, portable glossary, and legacy glossary paths."""
    if not game_root or not str(game_root).strip():
        return None
    root = Path(game_root).expanduser().resolve()
    if not root.is_dir():
        return (
            root,
            root / GAME_GLOSSARY_RELATIVE,
            root / LEGACY_GAME_GLOSSARY_RELATIVE,
        )
    game_metadata_dir(root)
    preferred = root / GAME_GLOSSARY_RELATIVE
    legacy = root / LEGACY_GAME_GLOSSARY_RELATIVE
    preferred_present = preferred.exists() or preferred.is_symlink()
    legacy_present = legacy.exists() or legacy.is_symlink()
    if preferred_present and (
        preferred.is_symlink() or not preferred.is_file()
    ):
        raise GameProjectPathError(
            f"Portable glossary path is not a regular file: {preferred}"
        )
    if legacy_present and (legacy.is_symlink() or not legacy.is_file()):
        raise GameProjectPathError(
            f"Legacy glossary path is not a regular file: {legacy}"
        )
    if (
        preferred_present
        and legacy_present
        and not _files_have_identical_content(preferred, legacy)
    ):
        raise GameProjectPathError(
            "Both the legacy and portable glossaries exist. DazedTL did not "
            f"overwrite either file:\n- {legacy}\n- {preferred}"
        )
    return root, preferred, legacy


def _files_have_identical_content(first: Path, second: Path) -> bool:
    """Compare regular files without trusting timestamps or cached metadata."""
    try:
        if first.stat().st_size != second.stat().st_size:
            return False
        with first.open("rb") as first_handle, second.open("rb") as second_handle:
            while True:
                first_chunk = first_handle.read(64 * 1024)
                second_chunk = second_handle.read(64 * 1024)
                if first_chunk != second_chunk:
                    return False
                if not first_chunk:
                    return True
    except OSError as exc:
        raise GameProjectPathError(
            f"Could not compare duplicate glossaries {first} and {second}: {exc}"
        ) from exc


def _remove_identical_legacy_glossary(preferred: Path, legacy: Path) -> None:
    """Remove a redundant root glossary, rechecking it immediately beforehand."""
    if not _files_have_identical_content(preferred, legacy):
        raise GameProjectPathError(
            "The legacy and portable glossaries changed while DazedTL was "
            f"preparing them. DazedTL did not overwrite either file:\n"
            f"- {legacy}\n- {preferred}"
        )
    try:
        legacy.unlink()
    except OSError as exc:
        raise GameProjectPathError(
            f"Could not remove redundant legacy glossary {legacy}: {exc}"
        ) from exc


def validate_game_glossary_migration(game_root: str | Path | None) -> None:
    """Validate a legacy glossary move without changing the selected game."""
    _game_glossary_paths(game_root)


def game_glossary_path(
    game_root: str | Path | None, *, migrate: bool = True
) -> Path | None:
    """Return the portable glossary path, optionally migrating the root file."""
    if not game_root or not str(game_root).strip():
        return None
    if not migrate:
        return Path(game_root).expanduser().resolve() / GAME_GLOSSARY_RELATIVE
    locations = _game_glossary_paths(game_root)
    if locations is None:
        return None
    root, preferred, legacy = locations
    if not root.is_dir():
        return preferred
    metadata = root / GAME_METADATA_RELATIVE
    preferred_present = preferred.exists() or preferred.is_symlink()
    legacy_present = legacy.exists() or legacy.is_symlink()
    ensure_game_tool_gitignore(root)
    if preferred_present and legacy_present:
        _remove_identical_legacy_glossary(preferred, legacy)
    elif legacy_present:
        metadata.mkdir(exist_ok=True)
        try:
            legacy.rename(preferred)
        except OSError as exc:
            raise GameProjectPathError(
                f"Could not move {legacy} to {preferred}: {exc}"
            ) from exc
    return preferred


def prepare_game_translation_context(
    game_root: str | Path, *, create_glossary: bool = True
) -> Path:
    """Prepare all portable guidance before translation workers are started.

    Logical conflicts are validated before the first rename. If a later rename
    fails, completed guidance moves are reversed so a game is not left partly
    migrated. The managed ``.gitignore`` block may remain after a rollback; it
    does not move or overwrite guidance content.
    """
    root = Path(game_root).expanduser().resolve()
    if not root.is_dir():
        raise GameProjectPathError(f"Game folder does not exist: {root}")

    # Import lazily: util.skills.system depends on this module's path constants.
    from util.skills.system import validate_game_skills_migration

    validate_game_glossary_migration(root)
    validate_game_skills_migration(root)
    ensure_game_tool_gitignore(root)

    game_metadata_dir(root, create=True)
    portable_glossary = root / GAME_GLOSSARY_RELATIVE
    legacy_glossary = root / LEGACY_GAME_GLOSSARY_RELATIVE
    portable_skills = root / GAME_SKILLS_RELATIVE
    legacy_skills = root / LEGACY_GAME_SKILLS_RELATIVE
    root_quirks = root / LEGACY_QUIRKS_FILENAME
    portable_quirks = root / GAME_QUIRKS_RELATIVE
    legacy_game_skill = root / LEGACY_GAME_SKILL_RELATIVE
    portable_game_skill = root / GAME_SKILL_RELATIVE
    completed_moves: list[tuple[Path, Path]] = []
    duplicate_glossary = (
        portable_glossary.is_file() and legacy_glossary.is_file()
    )

    def move(source: Path, destination: Path) -> None:
        if not (source.exists() or source.is_symlink()):
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
        completed_moves.append((source, destination))

    try:
        if not duplicate_glossary:
            move(legacy_glossary, portable_glossary)
        move(legacy_skills, portable_skills)
        # ``translation.md`` now lives inside the portable directory whether
        # that directory was just moved or already existed.
        move(legacy_game_skill, portable_game_skill)
        move(root_quirks, portable_quirks)
        # Delete an identical duplicate only after every fallible guidance move
        # succeeds, so rollback never needs to recreate a user file.
        if duplicate_glossary:
            _remove_identical_legacy_glossary(
                portable_glossary, legacy_glossary
            )
        if create_glossary and not portable_glossary.is_file():
            return ensure_game_glossary(root)
        return portable_glossary
    except Exception as exc:
        rollback_failures: list[str] = []
        for source, destination in reversed(completed_moves):
            try:
                if destination.exists() and not source.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    destination.rename(source)
            except OSError as rollback_exc:
                rollback_failures.append(
                    f"{destination} -> {source}: {rollback_exc}"
                )
        if rollback_failures:
            raise GameProjectPathError(
                f"Could not prepare portable game guidance: {exc}\n"
                "Rollback also failed:\n- " + "\n- ".join(rollback_failures)
            ) from exc
        if isinstance(exc, GameProjectPathError):
            raise
        raise GameProjectPathError(
            f"Could not prepare portable game guidance: {exc}"
        ) from exc


def _seed_game_glossary_text() -> str:
    """Build an empty game glossary with the current shipped base."""
    base_path = glossary_base_path()
    base = base_path.read_text(encoding="utf-8") if base_path.is_file() else ""
    return _EMPTY_GLOSSARY_PLACEHOLDER + "\n" + GLOSSARY_BASE_SEPARATOR + base


def ensure_game_glossary(game_root: str | Path | None) -> Path:
    """Create the selected game's glossary and return its path."""
    path = game_glossary_path(game_root)
    if path is None:
        raise ValueError("No game folder is selected.")
    root = path.parents[1]
    if not root.is_dir():
        raise FileNotFoundError(f"Game folder not found: {root}")
    if path.is_file():
        return path

    game_metadata_dir(root, create=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".glossary-", suffix=".tmp", dir=path.parent, text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_seed_game_glossary_text())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def active_glossary_path(*, create: bool = True) -> Path | None:
    """Resolve the explicitly selected or active-game translation glossary."""

    override = (os.getenv(GLOSSARY_OVERRIDE_ENV) or "").strip()
    if override:
        # A manual selection is always an existing user-owned file. Never seed
        # or migrate its parent as though it were a Workflow game directory.
        return Path(override).expanduser().resolve()

    root = (os.getenv("DAZED_GAME_ROOT") or "").strip()
    if not root:
        return None
    return (
        ensure_game_glossary(root)
        if create
        else game_glossary_path(root, migrate=False)
    )


def read_game_glossary(game_root: str | Path, *, create: bool = True) -> str:
    """Read one game's glossary, optionally previewing its seed without writing."""
    if create:
        path = game_glossary_path(game_root)
        locations = None
    else:
        locations = _game_glossary_paths(game_root)
        path = locations[1] if locations is not None else None
    if path is None:
        raise ValueError("No game folder is selected.")
    if path.is_file():
        return path.read_text(encoding="utf-8")
    if not create:
        root, _preferred, legacy = locations
        if legacy.is_file() and not legacy.is_symlink():
            return legacy.read_text(encoding="utf-8")
    if create:
        return ensure_game_glossary(game_root).read_text(encoding="utf-8")
    root = path.parents[1]
    if not root.is_dir():
        raise FileNotFoundError(f"Game folder not found: {root}")
    return _seed_game_glossary_text()


def read_active_glossary() -> str:
    """Read the active game's glossary, falling back to shipped base terms."""
    path = active_glossary_path()
    if path and path.is_file():
        text = path.read_text(encoding="utf-8")
        if (os.getenv(GLOSSARY_OVERRIDE_ENV) or "").strip():
            separator_index = text.find(GLOSSARY_BASE_SEPARATOR)
            custom = text[:separator_index] if separator_index >= 0 else text
            custom = custom.rstrip()
            include_base = (
                os.getenv(GLOSSARY_BASE_ENABLED_ENV, "true").strip().casefold()
                not in {"0", "false", "no", "off"}
            )
            if not include_base:
                return custom + ("\n" if custom else "")

            base_path = glossary_base_path()
            base = (
                base_path.read_text(encoding="utf-8")
                if base_path.is_file()
                else ""
            )
            if not base:
                return custom + ("\n" if custom else "")
            prefix = custom + "\n\n" if custom else ""
            return prefix + GLOSSARY_BASE_SEPARATOR + base
        return text
    base_path = glossary_base_path()
    return base_path.read_text(encoding="utf-8") if base_path.is_file() else ""
