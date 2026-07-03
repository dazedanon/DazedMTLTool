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

import os
import re
import threading

from util.paths import VOCAB_BASE_PATH, VOCAB_PATH

BASE_SEPARATOR = (
    "# ── Base Vocabulary (auto-appended from vocab_base.txt — do not edit below) ──\n"
)

_EMPTY_PLACEHOLDER = "# Add character glossary entries here\n"

# Guards the read-modify-write in update_vocab_section against concurrent
# translation file-threads clobbering each other's sections.
_VOCAB_LOCK = threading.Lock()


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


def _norm(s: str) -> str:
    """Normalise for no-op detection: collapse whitespace and case-fold."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


def update_vocab_section(category: str, pairs) -> None:
    """Insert or replace a ``# {category}`` section in the game-specific vocab.

    Mirrors the RPGMaker auto-glossary behaviour (translated DB names feed
    ``vocab.txt`` so later phases stay consistent), but always writes *above*
    the auto-appended base section (:data:`BASE_SEPARATOR`) so the base vocab is
    preserved and not stripped on the next :func:`read_game_vocab`.

    - ``category``: section header text, e.g. ``"Weapon · 武器"``.
    - ``pairs``: iterable of ``(source, translated)``. Deduped by source (last
      wins); no-ops (empty translation or unchanged after normalisation) are
      dropped. When nothing survives filtering the file is left untouched.
    """
    dedup: dict[str, str] = {}
    for src, dst in pairs:
        if not src:
            continue
        if dst is None or _norm(dst) == "" or _norm(dst) == _norm(src):
            continue
        dedup[str(src)] = str(dst)
    if not dedup:
        return

    with _VOCAB_LOCK:
        existing = VOCAB_PATH.read_text(encoding="utf-8") if VOCAB_PATH.is_file() else ""

        # Keep the auto-appended base section (separator + base vocab) intact.
        idx = existing.find(BASE_SEPARATOR)
        if idx != -1:
            game_part = existing[:idx]
            base_part = existing[idx:]
        else:
            game_part = existing
            base_part = ""

        block_lines = [f"{src} ({dst})" for src, dst in dedup.items()]
        new_block = f"# {category}\n" + "\n".join(block_lines) + "\n\n"

        # Match this category's section up to the next '#' header or end of the
        # game portion. Handles '#Cat', '# Cat', '## Cat', etc.
        pattern = re.compile(
            rf"^[\t ]*#+\s*{re.escape(category)}\s*$\r?\n.*?(?=^[\t ]*#|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        if pattern.search(game_part):
            new_game = pattern.sub(lambda _m: new_block, game_part, count=1)
        else:
            new_game = game_part.rstrip("\n")
            if new_game:
                new_game += "\n\n"
            new_game += new_block

        if base_part:
            combined = new_game.rstrip("\n") + "\n\n" + base_part
        else:
            combined = new_game

        if combined == existing:
            return

        tmp_path = VOCAB_PATH.with_suffix(
            VOCAB_PATH.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp"
        )
        tmp_path.write_text(combined, encoding="utf-8")
        os.replace(tmp_path, VOCAB_PATH)
