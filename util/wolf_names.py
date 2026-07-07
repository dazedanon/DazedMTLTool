"""WolfDawn ``names.json`` helpers for the WOLF translation workflow.

WolfDawn's ``names-extract`` produces ``names.json``: a project-wide glossary of
every value name the game references. Each entry has a ``source`` / ``text`` pair,
a ``note`` field (the WOLF database category it came from), and a static
``safety`` badge from WolfDawn's command-stream analysis:

* ``safe`` - display-only; no command references the string by name.
* ``refs`` - referenced by name, but WolfDawn rewrites every literal on inject.
* ``verify`` - also appears in indirect literals; left untranslated by default.

:mod:`modules.wolfdawn` translates only entries whose badge is ``safe`` or
``refs``. ``verify`` and legacy entries without a badge keep ``text == source``
so injection is a no-op for them.

Phase 0 still harvests translated **short name-like** entries into ``vocab.txt``,
grouped by ``note``. Multi-line profile blurbs, dialogue, and other content-shaped
names are translated in ``names.json`` but omitted from the glossary.
"""

from __future__ import annotations

import json
import re
from typing import Any

SAFETY_SAFE = "safe"
SAFETY_REFS = "refs"
SAFETY_VERIFY = "verify"
_TRANSLATABLE_SAFETY = frozenset({SAFETY_SAFE, SAFETY_REFS})

# names.json ``note`` values that are content fields, not short display names.
_VOCAB_SKIP_NOTE_RE = re.compile(
    r"プロフィール|説明|セリフ|台詞|会話|自己紹介|挨拶|モノローグ|独白",
)

# Short row labels and item/skill names fit; multi-line blurbs do not.
_VOCAB_HARVEST_MAX_LEN = 72

# WolfDawn labels standard database types bilingually in a document's group
# ``typeName`` (e.g. ``"Weapon · 武器"``). names.json ``note`` values are the JP
# half only, so this static map provides an English label for the common categories
# when the live DB labels are unavailable.
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

_LABEL_SEP = " · "


def parse_names_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    names = data.get("names", [])
    if not isinstance(names, list):
        return []
    return [entry for entry in names if isinstance(entry, dict)]


def has_safety_metadata(data: dict[str, Any]) -> bool:
    """True when *data* includes WolfDawn per-name ``safety`` badges."""
    return any("safety" in entry for entry in parse_names_entries(data))


def entry_safety(entry: dict[str, Any]) -> str:
    """Return the normalised ``safety`` badge for one names.json entry."""
    return str(entry.get("safety", "")).strip().lower()


def is_name_translatable(entry: dict[str, Any]) -> bool:
    """True when WolfDawn marks *entry* as safe or refs (per-name, not per-category)."""
    return entry_safety(entry) in _TRANSLATABLE_SAFETY


def is_vocab_harvest_candidate(entry: dict[str, Any]) -> bool:
    """True when a translated names.json entry should seed ``vocab.txt``.

    Translation uses :func:`is_name_translatable`; this is stricter. Profile text,
    multi-line blurbs, and dialogue-shaped strings are still translated in
    ``names.json`` but are not glossary terms.
    """
    if not is_name_translatable(entry):
        return False
    src = str(entry.get("source", ""))
    if not src.strip():
        return False
    if "\n" in src or "\r" in src:
        return False
    if len(src) > _VOCAB_HARVEST_MAX_LEN:
        return False
    note = str(entry.get("note", ""))
    if _VOCAB_SKIP_NOTE_RE.search(note):
        return False
    # Two or more sentence endings usually means dialogue, not a row label.
    if len(re.findall(r"[。！？]", src)) >= 2:
        return False
    return True


def count_name_safety(data: dict[str, Any]) -> dict[str, int]:
    """Return per-badge counts for a names.json document."""
    counts = {
        "total": 0,
        "safe": 0,
        "refs": 0,
        "verify": 0,
        "unknown": 0,
        "translatable": 0,
    }
    for entry in parse_names_entries(data):
        counts["total"] += 1
        safety = entry_safety(entry)
        if safety == SAFETY_SAFE:
            counts["safe"] += 1
        elif safety == SAFETY_REFS:
            counts["refs"] += 1
        elif safety == SAFETY_VERIFY:
            counts["verify"] += 1
        else:
            counts["unknown"] += 1
    counts["translatable"] = counts["safe"] + counts["refs"]
    return counts


def format_name_safety_summary(data: dict[str, Any]) -> str:
    """One-line summary for the workflow UI."""
    counts = count_name_safety(data)
    if not counts["total"]:
        return "No names found in names.json."
    if not has_safety_metadata(data):
        return (
            f"{counts['total']} name(s), but no WolfDawn safety badges - re-run names-extract "
            "with a current WolfDawn build before Phase 0."
        )
    parts = []
    if counts["safe"]:
        parts.append(f"{counts['safe']} safe")
    if counts["refs"]:
        parts.append(f"{counts['refs']} refs")
    if counts["verify"]:
        parts.append(f"{counts['verify']} verify")
    badge_text = ", ".join(parts) if parts else "no badges"
    return (
        f"{counts['translatable']} of {counts['total']} name(s) will translate "
        f"({badge_text}). Verify names are skipped."
    )


def derive_db_labels(files_dir) -> dict[str, str]:
    """Build a ``{japanese_note: english}`` map from staged WolfDawn ``db`` files."""
    from pathlib import Path

    labels: dict[str, str] = {}
    try:
        base = Path(files_dir)
        if not base.is_dir():
            return labels
        for path in sorted(base.glob("*.project.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            if doc.get("kind") != "db":
                continue
            for group in doc.get("groups") or []:
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
    """Return a bilingual vocab section header for a names.json ``note``."""
    english = (db_labels or {}).get(note) or NOTE_EN.get(note)
    if english and english != note:
        return f"{english}{_LABEL_SEP}{note}"
    return note


def collect_name_notes(data: dict[str, Any]) -> list[str]:
    """Return sorted unique ``note`` values from a names.json document."""
    notes: set[str] = set()
    for entry in parse_names_entries(data):
        note = str(entry.get("note", "")).strip()
        if note:
            notes.add(note)
    return sorted(notes)


def parse_name_wrap_notes(raw: str) -> frozenset[str]:
    """Parse ``wolfNameWrapNotes`` from ``.env`` (JSON array or comma-separated)."""
    text = (raw or "").strip()
    if not text:
        return frozenset()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return frozenset(str(item).strip() for item in parsed if str(item).strip())
    except json.JSONDecodeError:
        pass
    return frozenset(part.strip() for part in text.split(",") if part.strip())


def load_name_wrap_config() -> tuple[bool, int, frozenset[str]]:
    """Return ``(enabled, width, notes)`` from workflow ``.env`` settings."""
    import os

    enabled = os.getenv("wolfNameWrap", "false").strip().lower() == "true"
    try:
        width = int(os.getenv("wolfNameWrapWidth") or 0)
    except ValueError:
        width = 0
    notes = parse_name_wrap_notes(os.getenv("wolfNameWrapNotes", ""))
    return enabled, width, notes
