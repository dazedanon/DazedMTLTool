"""Canonical project paths (repo root, data files, config)."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
VOCAB_PATH = DATA_DIR / "vocab.txt"
VOCAB_BASE_PATH = DATA_DIR / "vocab_base.txt"
PROMPT_PATH = DATA_DIR / "prompt.txt"
LAST_UPDATE_SHA_PATH = DATA_DIR / "last_update_sha.txt"
ENV_PATH = PROJECT_ROOT / ".env"
ICON_PATH = PROJECT_ROOT / "assets" / "icon.png"
ENGINE_ICONS_DIR = PROJECT_ROOT / "assets" / "engine_icons"

_ROOT_DATA_FILES = (
    "vocab.txt",
    "vocab_base.txt",
    "prompt.txt",
    "last_update_sha.txt",
)


def migrate_root_data_files() -> None:
    """Move legacy root-level data files into data/ on first run."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in _ROOT_DATA_FILES:
        src = PROJECT_ROOT / name
        dst = DATA_DIR / name
        if src.is_file() and not dst.exists():
            src.rename(dst)


migrate_root_data_files()


def ensure_vocab_file() -> None:
    """Create data/vocab.txt from vocab_base.txt when missing."""
    migrate_root_data_files()
    if VOCAB_PATH.is_file():
        return
    if VOCAB_BASE_PATH.is_file():
        VOCAB_PATH.write_text(VOCAB_BASE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        VOCAB_PATH.write_text("", encoding="utf-8")
