"""Canonical project paths (repo root, data files, config)."""

from __future__ import annotations

from pathlib import Path

# Product identity (QSettings / desktop / window titles).
ORG_NAME = "DazedTranslations"
APP_NAME = "DazedTL"
LEGACY_APP_NAME = "DazedMTLTool"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
GLOSSARY_FILENAME = "glossary.txt"
LEGACY_GLOSSARY_FILENAME = "vocab.txt"
GLOSSARY_BASE_PATH = DATA_DIR / "glossary_base.txt"
LEGACY_GLOSSARY_BASE_PATH = DATA_DIR / "vocab_base.txt"
LEGACY_GLOBAL_GLOSSARY_PATH = DATA_DIR / LEGACY_GLOSSARY_FILENAME
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
# Per-game quirks skill (API overlay). Legacy flat file still migrated on load.
GAME_QUIRKS_RELATIVE = Path("skills") / "quirks.md"
LEGACY_QUIRKS_FILENAME = "translation_quirks.txt"
GAME_SKILL_RELATIVE = Path("skills") / "game.md"
LEGACY_GAME_SKILL_RELATIVE = Path("skills") / "translation.md"
# Built-in skill filenames under <game>/skills/ (not user-custom overlays).
GAME_SKILL_RESERVED_NAMES = frozenset({"quirks.md", "game.md", "translation.md"})

_ROOT_DATA_FILES = (
    "vocab.txt",
    "vocab_base.txt",
    "prompt.txt",
    "last_update_sha.txt",
)

GLOSSARY_BASE_SEPARATOR = (
    "# ── Base Glossary (auto-appended from glossary_base.txt — do not edit below) ──\n"
)
LEGACY_GLOSSARY_BASE_SEPARATOR = (
    "# ── Base Vocabulary (auto-appended from vocab_base.txt — do not edit below) ──\n"
)
_EMPTY_GLOSSARY_PLACEHOLDER = "# Add character glossary entries here\n"


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


migrate_root_data_files()
migrate_prompt_to_skills()


def glossary_base_path() -> Path:
    """Return the shipped base glossary, including the legacy upgrade path."""
    if GLOSSARY_BASE_PATH.is_file():
        return GLOSSARY_BASE_PATH
    return LEGACY_GLOSSARY_BASE_PATH


def game_glossary_path(game_root: str | Path | None) -> Path | None:
    """Return ``<game_root>/glossary.txt`` when a game root is available."""
    if not game_root or not str(game_root).strip():
        return None
    return Path(game_root).expanduser().resolve() / GLOSSARY_FILENAME


def _seed_game_glossary_text(path: Path) -> str:
    """Build the initial glossary text without changing the selected game."""
    for legacy in (
        path.with_name(LEGACY_GLOSSARY_FILENAME),
        LEGACY_GLOBAL_GLOSSARY_PATH,
    ):
        if not legacy.is_file():
            continue
        try:
            legacy_text = legacy.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            legacy_text = ""
        if (
            LEGACY_GLOSSARY_BASE_SEPARATOR in legacy_text
            or GLOSSARY_BASE_SEPARATOR in legacy_text
        ):
            separator_indexes = [
                legacy_text.find(separator)
                for separator in (
                    LEGACY_GLOSSARY_BASE_SEPARATOR,
                    GLOSSARY_BASE_SEPARATOR,
                )
                if legacy_text.find(separator) >= 0
            ]
            custom_text = legacy_text[:min(separator_indexes)].rstrip("\n")
            base_path = glossary_base_path()
            base = (
                base_path.read_text(encoding="utf-8")
                if base_path.is_file()
                else ""
            )
            return custom_text + "\n\n" + GLOSSARY_BASE_SEPARATOR + base

    base_path = glossary_base_path()
    base = base_path.read_text(encoding="utf-8") if base_path.is_file() else ""
    return _EMPTY_GLOSSARY_PLACEHOLDER + "\n" + GLOSSARY_BASE_SEPARATOR + base


def ensure_game_glossary(game_root: str | Path | None) -> Path:
    """Create or safely copy the selected game's glossary and return its path.

    Older DazedTL versions copied ``vocab.txt`` into the game root. Copy that
    file only when its DazedTL base marker proves its provenance. Keep the legacy
    file as a backup; an unrelated game-owned ``vocab.txt`` must never be moved.
    """
    path = game_glossary_path(game_root)
    if path is None:
        raise ValueError("No game folder is selected.")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"Game folder not found: {path.parent}")
    if path.is_file():
        return path

    # Prefer a glossary that already lived with this game. Older releases used
    # one global data/vocab.txt instead; seed every newly selected game from
    # that file so upgrades do not silently lose the user's custom terms.
    path.write_text(_seed_game_glossary_text(path), encoding="utf-8")
    return path


def active_glossary_path(*, create: bool = True) -> Path | None:
    """Resolve the glossary for the game active in the translation process."""
    import os

    root = (os.getenv("DAZED_GAME_ROOT") or "").strip()
    if not root:
        return None
    return ensure_game_glossary(root) if create else game_glossary_path(root)


def read_game_glossary(game_root: str | Path, *, create: bool = True) -> str:
    """Read one game's glossary, optionally previewing its seed without writing."""
    path = game_glossary_path(game_root)
    if path is None:
        raise ValueError("No game folder is selected.")
    if path.is_file():
        return path.read_text(encoding="utf-8")
    if create:
        return ensure_game_glossary(game_root).read_text(encoding="utf-8")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"Game folder not found: {path.parent}")
    return _seed_game_glossary_text(path)


def read_active_glossary() -> str:
    """Read the active game's glossary, falling back to shipped base terms."""
    path = active_glossary_path()
    if path and path.is_file():
        return path.read_text(encoding="utf-8")
    base_path = glossary_base_path()
    return base_path.read_text(encoding="utf-8") if base_path.is_file() else ""
