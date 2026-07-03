"""Safe-to-translate ``note`` categories for the WOLF (WolfDawn) name glossary.

WolfDawn's ``names-extract`` produces ``names.json``: a project-wide list of every
"value name" the game references (item / skill / enemy names, but also variable
names, file/SE/BGM keys, event names, map settings, ...). Each entry carries a
``note`` field naming the WOLF database category it came from, e.g. ``武器``
(weapons), ``技能`` (skills), ``システム変数名`` (system variable names).

Translating *all* of them corrupts the game, because many categories are logic
keys (compared by value, used to build filenames, stored in variables). Only the
categories that are pure on-screen text are safe to translate.

Rather than hand-editing 2000+ entries, the workflow classifies by ``note``: a
repo-aware AI decides which *categories* are display-only, and that short list is
saved here. The WolfDawn translation module (:mod:`modules.wolfdawn`) then only
translates ``names.json`` entries whose ``note`` is in the safe list, leaving
everything else identical to the source (so injection is a no-op for it).

The default is an empty list: nothing is translated until the user opts a
category in, which keeps the safe-by-default behaviour the workflow relies on.
"""

from __future__ import annotations

import json

from util.paths import DATA_DIR

SAFE_NOTES_PATH = DATA_DIR / "wolf_safe_notes.json"


def load_safe_notes() -> list[str]:
    """Return the saved list of ``note`` categories that are safe to translate."""
    try:
        if SAFE_NOTES_PATH.is_file():
            data = json.loads(SAFE_NOTES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(n) for n in data]
    except Exception:
        pass
    return []


def save_safe_notes(notes: list[str]) -> None:
    """Persist the safe ``note`` categories (de-duplicated, order preserved)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for note in notes:
        note = str(note)
        if note not in seen:
            seen.add(note)
            ordered.append(note)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SAFE_NOTES_PATH.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=4), encoding="utf-8"
    )


def is_note_safe(note: str, safe_notes) -> bool:
    """True if *note* is in the *safe_notes* collection."""
    if not safe_notes:
        return False
    return note in safe_notes
