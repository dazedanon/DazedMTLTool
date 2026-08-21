"""Shared helpers for ``<game>/.dazedtl/glossary.txt``.

``glossary.txt`` is loaded by the shared translation layer (:mod:`util.translation`)
and applied to every engine, so a good glossary keeps character names, honorifics,
and worldbuilding terms consistent across the whole translation.

The file has two parts:

* the game-specific entries (characters, worldbuilding terms) edited per project,
* a base glossary that is auto-appended from ``data/glossary_base.txt``.

``BASE_SEPARATOR`` marks where the auto-appended base section begins so the
workflow editors can show and save only the game-specific portion.
"""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from pathlib import Path

from util.paths import (
    GLOSSARY_BASE_SEPARATOR,
    active_glossary_path,
    ensure_game_glossary,
    glossary_base_path,
    read_active_glossary,
    read_game_glossary,
)

BASE_SEPARATOR = GLOSSARY_BASE_SEPARATOR

_EMPTY_PLACEHOLDER = "# Add character glossary entries here\n"

# Guards the read-modify-write in update_vocab_section against concurrent
# translation file-threads clobbering each other's sections.
_VOCAB_LOCK = threading.Lock()

# Collect freezes the glossary for collect-time prompts and for rematching
# legacy (pre-v5) paid batch results after Pass 2 harvests names.
BATCH_GLOSSARY_FREEZE_FILE = Path("log/batch_glossary_freeze.txt")


def _path(game_root) -> "Path":
    if game_root is not None:
        return ensure_game_glossary(game_root)
    path = active_glossary_path()
    if path is None:
        raise RuntimeError("No active game folder is available for glossary access.")
    return path


def batch_glossary_phase() -> str:
    """Return the active batch phase, or ``\"\"`` when batch translation is off."""
    return (os.getenv("BATCH_PHASE") or "").strip().lower()


def freeze_batch_glossary(*, game_root=None) -> Path:
    """Snapshot the live glossary for the current batch collect/consume cycle."""
    text = read_active_glossary() if game_root is None else _path(game_root).read_text(
        encoding="utf-8"
    )
    return write_batch_glossary_freeze(text)


def write_batch_glossary_freeze(text: str) -> Path:
    """Write an explicit freeze snapshot (used when restoring from history)."""
    text = text if isinstance(text, str) else ""
    BATCH_GLOSSARY_FREEZE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BATCH_GLOSSARY_FREEZE_FILE.with_suffix(
        BATCH_GLOSSARY_FREEZE_FILE.suffix
        + f".{os.getpid()}.{threading.get_ident()}.tmp"
    )
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, BATCH_GLOSSARY_FREEZE_FILE)
    return BATCH_GLOSSARY_FREEZE_FILE


def persist_batch_glossary_freeze_to_state() -> None:
    """Copy the freeze file into active batch_state for redownload/resume."""
    if not BATCH_GLOSSARY_FREEZE_FILE.is_file():
        return
    try:
        text = BATCH_GLOSSARY_FREEZE_FILE.read_text(encoding="utf-8")
        import util.translation as T

        with T.BATCH_LOCK:
            with T._batch_file_lock():
                state = T._read_batch_file(T.BATCH_STATE_FILE)
                state["glossary_freeze"] = text
                T._write_batch_file(T.BATCH_STATE_FILE, state)
    except Exception:
        pass


def restore_batch_glossary_freeze_from_state() -> bool:
    """Restore the freeze file from active batch_state when missing."""
    if BATCH_GLOSSARY_FREEZE_FILE.is_file():
        return True
    try:
        import util.translation as T

        with T._batch_file_lock():
            state = T._read_batch_file(T.BATCH_STATE_FILE)
        text = state.get("glossary_freeze")
        if not isinstance(text, str) or not text:
            return False
        write_batch_glossary_freeze(text)
        return True
    except Exception:
        return False


def clear_batch_glossary_freeze() -> None:
    """Drop the collect-time glossary freeze, if present."""
    try:
        if BATCH_GLOSSARY_FREEZE_FILE.exists():
            BATCH_GLOSSARY_FREEZE_FILE.unlink()
    except Exception:
        pass


def read_translation_glossary() -> str:
    """Glossary text preferred during batch collect (freeze) or otherwise live.

    During collect, prefer the freeze taken at collect start. During consume,
    callers that need live harvests should read the live glossary; batch result
    keys use the freeze only for legacy (pre-v5) rematching.
    """
    if batch_glossary_phase() == "collect":
        if BATCH_GLOSSARY_FREEZE_FILE.is_file():
            try:
                return BATCH_GLOSSARY_FREEZE_FILE.read_text(encoding="utf-8")
            except OSError:
                pass
        restore_batch_glossary_freeze_from_state()
        if BATCH_GLOSSARY_FREEZE_FILE.is_file():
            try:
                return BATCH_GLOSSARY_FREEZE_FILE.read_text(encoding="utf-8")
            except OSError:
                pass
    return read_active_glossary()


def _split_base(text: str) -> tuple[str, str]:
    index = text.find(BASE_SEPARATOR)
    if index == -1:
        return text, ""
    return text[:index], text[index:]


def read_game_vocab(game_root=None, *, create: bool = True) -> str:
    """Return the game section, optionally previewing a missing glossary read-only."""
    if create:
        text = _path(game_root).read_text(encoding="utf-8")
    elif game_root is not None:
        text = read_game_glossary(game_root, create=False)
    else:
        path = active_glossary_path(create=False)
        if path is None:
            return _EMPTY_PLACEHOLDER
        text = read_game_glossary(path.parents[1], create=False)
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

_DECORATIVE_GLOSSARY_PUNCTUATION = frozenset({"•", "‣", "⁃", "※"})


def split_glossary_decorative_prefix(term: str) -> tuple[str, str]:
    """Return a leading label marker and the usable term behind it.

    Unicode ``So`` characters cover geometric markers such as ``▼``, ``■``,
    and ``★`` without classifying parentheses or percent signs as decoration.
    The explicit punctuation set covers common bullet and note markers used by
    game databases.
    """
    text = str(term or "").strip()
    marker_end = 0
    while marker_end < len(text):
        char = text[marker_end]
        if (
            unicodedata.category(char) == "So"
            or char in _DECORATIVE_GLOSSARY_PUNCTUATION
        ):
            marker_end += 1
            continue
        break
    if marker_end == 0:
        return "", text
    return text[:marker_end], text[marker_end:].lstrip()


def decorative_glossary_alias(source: str, target: str):
    """Return a clean alias when an existing row uses the same paired marker."""
    source_marker, source_alias = split_glossary_decorative_prefix(source)
    target_marker, target_alias = split_glossary_decorative_prefix(target)
    if (
        not source_marker
        or source_marker != target_marker
        or not source_alias
        or not target_alias
    ):
        return None
    return source_alias, target_alias


def normalize_generated_glossary_pair(source: str, target: str) -> tuple[str, str]:
    """Remove leading database-label decoration from a generated pair."""
    _source_marker, clean_source = split_glossary_decorative_prefix(source)
    _target_marker, clean_target = split_glossary_decorative_prefix(target)
    return clean_source, clean_target


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


def update_vocab_section(
    category: str, pairs, *, merge: bool = False, game_root=None
) -> None:
    """Insert or replace a ``# {category}`` section in the game-specific vocab.

    Mirrors the RPGMaker auto-glossary behaviour (translated DB names feed
    ``glossary.txt`` so later phases stay consistent), but always writes *above*
    the auto-appended base section (:data:`BASE_SEPARATOR`) so the base glossary is
    preserved and not stripped on the next :func:`read_game_vocab`.

    - ``category``: section header text, e.g. ``"Weapon · 武器"``.
    - ``pairs``: iterable of ``(source, translated)``. Deduped by source (last
      wins); no-ops (empty translation or unchanged after normalisation) are
      dropped. Leading database-label decoration is removed from generated
      rows. When nothing survives filtering the file is left untouched.
    - ``merge``: when True, keep existing entries for this category and only add
      sources that are not already present (names.json stays authoritative).

    Collect skips writes (source text is still untranslated). Consume writes
    immediately so sequential Pass 2 files can load harvested names.
    """
    dedup: dict[str, str] = {}
    for src, dst in pairs:
        src, dst = normalize_generated_glossary_pair(src, dst)
        if not src:
            continue
        if dst is None or _norm(dst) == "" or _norm(dst) == _norm(src):
            continue
        dedup[str(src)] = str(dst)
    if not dedup:
        return

    if batch_glossary_phase() == "collect":
        # Collect leaves source text untranslated; nothing useful to harvest.
        return

    with _VOCAB_LOCK:
        glossary_path = _path(game_root)
        existing = glossary_path.read_text(encoding="utf-8")

        # Keep the auto-appended base section (separator + base glossary) intact.
        game_part, base_part = _split_base(existing)

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
