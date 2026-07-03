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

# WolfDawn labels standard database types bilingually in a document's group
# ``typeName`` (e.g. ``"Weapon · 武器"``). names.json ``note`` values are the JP
# half only, so this static map provides an English label for the common,
# safe-to-translate categories when the live DB labels are unavailable. Games
# with custom categories fall back to a JP-only header.
NOTE_EN: dict[str, str] = {
    "武器": "Weapon",
    "防具": "Armor",
    "技能": "Skill",
    "アイテム": "Item",
    "状態設定": "State Setting",
    "用語設定": "Term Setting",
    "戦闘コマンド": "Battle Command",
    "システム設定": "System Setting",
    "属性名の設定": "Attribute",
    "主人公ステータス": "Hero Status",
    "敵グループ": "Enemy Group",
    "敵ｷｬﾗ個体ﾃﾞｰﾀ": "Enemy Data",
}

# WolfDawn joins the English and Japanese halves of a database label with this
# separator, e.g. ``"Weapon · 武器"``.
_LABEL_SEP = " · "


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


def derive_db_labels(files_dir) -> dict[str, str]:
    """Build a ``{japanese_note: english}`` map from staged WolfDawn ``db`` files.

    WolfDawn tags each database group with a bilingual ``typeName`` (e.g.
    ``"Weapon · 武器"``). Splitting on the separator recovers the game-accurate
    English label for a names.json ``note`` (the JP half), so harvested vocab
    sections can be headed bilingually without hardcoding categories per game.
    """
    from pathlib import Path

    labels: dict[str, str] = {}
    try:
        base = Path(files_dir)
        if not base.is_dir():
            return labels
        for path in sorted(base.glob("*.project.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            if data.get("kind") != "db":
                continue
            for group in data.get("groups") or []:
                type_name = group.get("typeName") or ""
                if _LABEL_SEP in type_name:
                    english, _, japanese = type_name.partition(_LABEL_SEP)
                    english, japanese = english.strip(), japanese.strip()
                    if english and japanese and japanese not in labels:
                        labels[japanese] = english
    except Exception:
        pass
    return labels


def note_header(note: str, db_labels: dict[str, str] | None = None) -> str:
    """Return a bilingual vocab section header for a names.json ``note``.

    Prefers the live DB label (:func:`derive_db_labels`), then the static
    :data:`NOTE_EN` map, and falls back to the JP note alone. Formats matching
    WolfDawn's own labels, e.g. ``"Weapon · 武器"``.
    """
    english = (db_labels or {}).get(note) or NOTE_EN.get(note)
    if english and english != note:
        return f"{english}{_LABEL_SEP}{note}"
    return note
