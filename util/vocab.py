"""Shared helpers for the game-specific translation glossary (``<game>/glossary.txt``).

``glossary.txt`` is loaded by the shared translation layer (:mod:`util.translation`)
and applied to every engine, so a good glossary keeps character names, honorifics,
and worldbuilding terms consistent across the whole translation.

The file has two parts:

* the game-specific entries (characters, worldbuilding terms) edited per project,
* a base glossary that is auto-appended from ``data/glossary_base.txt``.

``BASE_SEPARATOR`` marks where the auto-appended base section begins so the
workflow editors can show and save only the game-specific portion. The legacy
separator remains recognized so game-local ``vocab.txt`` files from
older versions can be migrated without exposing the base section in the editor.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from util.paths import (
    GLOSSARY_BASE_SEPARATOR,
    LEGACY_GLOSSARY_BASE_SEPARATOR,
    active_glossary_path,
    ensure_game_glossary,
    glossary_base_path,
)

BASE_SEPARATOR = GLOSSARY_BASE_SEPARATOR
_BASE_SEPARATORS = (BASE_SEPARATOR, LEGACY_GLOSSARY_BASE_SEPARATOR)

_EMPTY_PLACEHOLDER = "# Add character glossary entries here\n"

# Guards the read-modify-write in update_vocab_section against concurrent
# translation file-threads clobbering each other's sections.
_VOCAB_LOCK = threading.Lock()


def _path(game_root) -> "Path":
    if game_root is not None:
        return ensure_game_glossary(game_root)
    path = active_glossary_path()
    if path is None:
        raise RuntimeError("No active game folder is available for glossary access.")
    return path


def _split_base(text: str) -> tuple[str, str]:
    indexes = [(text.find(separator), separator) for separator in _BASE_SEPARATORS]
    indexes = [(idx, separator) for idx, separator in indexes if idx != -1]
    if not indexes:
        return text, ""
    idx, _separator = min(indexes, key=lambda item: item[0])
    return text[:idx], text[idx:]


def read_game_vocab(game_root=None) -> str:
    """Return the game-specific portion of ``glossary.txt`` (base stripped)."""
    path = _path(game_root)
    text = path.read_text(encoding="utf-8")
    game_part, _base_part = _split_base(text)
    return game_part.rstrip("\n") or _EMPTY_PLACEHOLDER


def write_game_vocab(game_text: str, game_root=None) -> None:
    """Write the game-specific glossary and re-append the shipped base."""
    game_text = (game_text or "").rstrip("\n")
    base_path = glossary_base_path()
    base_text = (
        base_path.read_text(encoding="utf-8") if base_path.is_file() else ""
    )
    combined = game_text + "\n\n" + BASE_SEPARATOR + base_text
    _path(game_root).write_text(combined, encoding="utf-8")


def _norm(s: str) -> str:
    """Normalise for no-op detection: collapse whitespace and case-fold."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


_SECTION_PAIR_RE = re.compile(
    r"^(.+?)\s+\((.+)\)\s*$",
)


def _parse_section_pairs(section_body: str) -> dict[str, str]:
    """Parse ``src (dst)`` lines from a vocab section body (no header)."""
    pairs: dict[str, str] = {}
    for raw in section_body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _SECTION_PAIR_RE.match(line)
        if not m:
            continue
        pairs[m.group(1)] = m.group(2)
    return pairs


def update_vocab_section(category: str, pairs, *, merge: bool = False, game_root=None) -> None:
    """Insert or replace a ``# {category}`` section in the game-specific vocab.

    Mirrors the RPGMaker auto-glossary behaviour (translated DB names feed
    ``glossary.txt`` so later phases stay consistent), but always writes *above*
    the auto-appended base section (:data:`BASE_SEPARATOR`) so the base glossary is
    preserved and not stripped on the next :func:`read_game_vocab`.

    - ``category``: section header text, e.g. ``"Weapon · 武器"``.
    - ``pairs``: iterable of ``(source, translated)``. Deduped by source (last
      wins); no-ops (empty translation or unchanged after normalisation) are
      dropped. When nothing survives filtering the file is left untouched.
    - ``merge``: when True, keep existing entries for this category and only add
      sources that are not already present (names.json stays authoritative).
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
        glossary_path = _path(game_root)
        existing = glossary_path.read_text(encoding="utf-8")

        # Keep the auto-appended base section (separator + base vocab) intact.
        game_part, base_part = _split_base(existing)
        if base_part.startswith(LEGACY_GLOSSARY_BASE_SEPARATOR):
            base_path = glossary_base_path()
            base_text = base_path.read_text(encoding="utf-8") if base_path.is_file() else ""
            base_part = BASE_SEPARATOR + base_text

        # Match this category's section up to the next '#' header or end of the
        # game portion. Handles '#Cat', '# Cat', '## Cat', etc.
        pattern = re.compile(
            rf"^([\t ]*#+\s*{re.escape(category)}\s*$\r?\n)(.*?)(?=^[\t ]*#|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(game_part)
        if merge and match:
            merged = _parse_section_pairs(match.group(2))
            for src, dst in dedup.items():
                if src not in merged:
                    merged[src] = dst
            dedup = merged
            if not dedup:
                return

        block_lines = [f"{src} ({dst})" for src, dst in dedup.items()]
        new_block = f"# {category}\n" + "\n".join(block_lines) + "\n\n"

        if match:
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

        tmp_path = glossary_path.with_suffix(
            glossary_path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp"
        )
        tmp_path.write_text(combined, encoding="utf-8")
        os.replace(tmp_path, glossary_path)


def remove_vocab_section(category: str, *, game_root=None) -> None:
    """Remove a ``# {category}`` section from the game-specific vocab, if present."""
    with _VOCAB_LOCK:
        glossary_path = _path(game_root)
        existing = glossary_path.read_text(encoding="utf-8")

        game_part, base_part = _split_base(existing)

        pattern = re.compile(
            rf"^[\t ]*#+\s*{re.escape(category)}\s*$\r?\n.*?(?=^[\t ]*#|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        new_game = pattern.sub("", game_part, count=1)
        if new_game == game_part:
            return
        new_game = re.sub(r"\n{3,}", "\n\n", new_game).rstrip("\n")
        if base_part:
            combined = new_game + "\n\n" + base_part if new_game else base_part
        else:
            combined = new_game + "\n" if new_game else ""
        if combined == existing:
            return
        tmp_path = glossary_path.with_suffix(
            glossary_path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp"
        )
        tmp_path.write_text(combined, encoding="utf-8")
        os.replace(tmp_path, glossary_path)
