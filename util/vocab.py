"""Shared helpers for the game-specific translation glossary (``data/vocab.txt``).

``vocab.txt`` is loaded by the shared translation layer (:mod:`util.translation`)
and applied to every engine, so a good glossary keeps character names, honorifics,
and worldbuilding terms consistent across the whole translation.

The file has two parts:

* the game-specific entries (characters, worldbuilding terms) edited per project,
* a base vocabulary that is auto-appended from ``data/vocab_base.txt``.

``BASE_SEPARATOR`` marks where the auto-appended base section begins so the
workflow editors can show and save only the game-specific portion. It must stay
byte-identical to what has already been written into users' ``vocab.txt`` files,
otherwise the base section would not be stripped on reload.
"""

from __future__ import annotations

from util.paths import VOCAB_BASE_PATH, VOCAB_PATH

BASE_SEPARATOR = (
    "# ── Base Vocabulary (auto-appended from vocab_base.txt — do not edit below) ──\n"
)

_EMPTY_PLACEHOLDER = "# Add character glossary entries here\n"


def read_game_vocab() -> str:
    """Return the game-specific portion of ``vocab.txt`` (base section stripped)."""
    if VOCAB_PATH.is_file():
        text = VOCAB_PATH.read_text(encoding="utf-8")
        idx = text.find(BASE_SEPARATOR)
        if idx != -1:
            text = text[:idx].rstrip("\n")
        return text
    return _EMPTY_PLACEHOLDER


def write_game_vocab(game_text: str) -> None:
    """Write the game-specific vocab and re-append the base vocabulary."""
    game_text = (game_text or "").rstrip("\n")
    base_text = (
        VOCAB_BASE_PATH.read_text(encoding="utf-8") if VOCAB_BASE_PATH.is_file() else ""
    )
    combined = game_text + "\n\n" + BASE_SEPARATOR + base_text
    VOCAB_PATH.write_text(combined, encoding="utf-8")
