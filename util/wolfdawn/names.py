"""WolfDawn ``names.json`` helpers for the WOLF translation workflow.

WolfDawn's ``names-extract`` produces ``names.json``: a project-wide glossary of
every value name the game references. Each entry has a ``source`` / ``text`` pair,
a ``note`` field (the WOLF database category it came from), and a static
``safety`` badge from WolfDawn's command-stream analysis:

* ``safe`` - display-only; no command references the string by name.
* ``refs`` - referenced by name (picture codes, switch labels, etc.); skipped.
* ``verify`` - also appears in indirect literals; left untranslated by default.

:mod:`modules.wolfdawn` translates only entries whose badge is ``safe``.
``refs``, ``verify``, and legacy entries without a badge keep ``text == source``
so injection is a no-op for them.

Phase 0 still harvests translated **short name-like** entries into ``vocab.txt``,
grouped by ``note``. Multi-line profile blurbs, dialogue, and other content-shaped
names are translated in ``names.json`` but omitted from the glossary.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Union

PathLike = Union[str, Path]

SAFETY_SAFE = "safe"
SAFETY_REFS = "refs"
SAFETY_VERIFY = "verify"
_TRANSLATABLE_SAFETY = frozenset({SAFETY_SAFE})

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
    """True when WolfDawn marks *entry* as safe (per-name, not per-category)."""
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
    counts["translatable"] = counts["safe"]
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
        f"({badge_text}). Refs and verify names are skipped."
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


def format_note_category_summary(
    data: dict[str, Any],
    *,
    top_n: int = 8,
    db_labels: dict[str, str] | None = None,
) -> str:
    """Multi-line breakdown of top ``note`` categories for the Names workflow step."""
    from collections import Counter

    counts: Counter[str] = Counter()
    for entry in parse_names_entries(data):
        note = str(entry.get("note", "")).strip()
        if note:
            counts[note] += 1
    if not counts:
        return "No note categories found."
    lines = [f"Top categories in this game ({len(counts)} unique):"]
    for note, count in counts.most_common(top_n):
        header = note_header(note, db_labels)
        lines.append(f"  {count:4d}  {header}")
    remaining = len(counts) - min(top_n, len(counts))
    if remaining > 0:
        lines.append(f"  … and {remaining} more categor{'y' if remaining == 1 else 'ies'}")
    return "\n".join(lines)


def collect_name_notes(data: dict[str, Any]) -> list[str]:
    """Return sorted unique ``note`` values from a names.json document."""
    notes: set[str] = set()
    for entry in parse_names_entries(data):
        note = str(entry.get("note", "")).strip()
        if note:
            notes.add(note)
    return sorted(notes)


def apply_names_wrap(
    names_path: PathLike,
    *,
    note: str | None = None,
    width: int | None = None,
    lines: int | None = None,
    dry_run: bool = False,
    log_fn=None,
) -> tuple[bool, str]:
    """Run ``wolf names-wrap`` on one names.json file.

    When *note* is set, only that category (``names[].note``) is processed.
    Omit *width* / *lines* to measure slot geometry from JP text (recommended).

    Returns ``(ok, summary)``. *ok* is False only when the CLI exits with a hard
    error; overflow warnings still count as success.
    """
    from util import wolfdawn

    emit = log_fn or (lambda _msg: None)
    path = Path(names_path)
    if not path.is_file():
        return False, f"names.json not found: {path}"

    res = wolfdawn.names_wrap(
        path,
        note=note,
        width=width,
        lines=lines,
        dry_run=dry_run,
        log_fn=None,
    )
    for line in (res.stdout or "").splitlines():
        line = line.strip()
        if line:
            emit(line)
    for line in (res.stderr or "").splitlines():
        line = line.strip()
        if line:
            emit(line)

    if not res.ok and res.returncode not in (0, 2):
        return False, f"names-wrap exited {res.returncode}"

    count = wolfdawn.parse_names_wrap_counts(res.stdout, res.stderr)
    shrunk = wolfdawn.parse_names_wrap_shrink_count(res.stdout, res.stderr)
    scope = f"category {note}" if note else "names.json"
    parts: list[str] = []
    if dry_run:
        if count is not None:
            parts.append(
                f"dry run: {count} entr{'y' if count == 1 else 'ies'} in {scope} "
                "would be re-wrapped"
            )
        else:
            parts.append(f"dry run complete for {scope}")
    elif count is not None:
        parts.append(
            f"re-wrapped {count} entr{'y' if count == 1 else 'ies'} in {scope}"
        )
    else:
        parts.append(f"names-wrap complete for {scope}")
    if width is not None and int(width) > 0:
        parts.append(f"width={int(width)}")
    if lines is not None and int(lines) > 0:
        parts.append(f"lines={int(lines)}")
    if shrunk:
        parts.append(f"{shrunk} shrunk with \\f[N]")
    return True, "; ".join(parts)


def roles_json_path_for_names(names_path: PathLike) -> Path:
    """Return ``wolfdawn-roles.json`` beside *names_path* (WolfDawn looks there)."""
    return Path(names_path).resolve().parent / "wolfdawn-roles.json"


def load_name_wrap_roles(roles_path: PathLike) -> dict[str, Any]:
    """Load ``wolfdawn-roles.json``, or an empty document."""
    path = Path(roles_path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_name_wrap_role(roles: dict[str, Any], note: str) -> dict[str, Any] | None:
    """Return the ``nameWraps`` entry matching *note*, if any."""
    wraps = roles.get("nameWraps")
    if not isinstance(wraps, list):
        return None
    for entry in wraps:
        if not isinstance(entry, dict):
            continue
        entry_note = str(entry.get("note") or "")
        if entry_note == note or (note and note in entry_note) or (entry_note and entry_note in note):
            return entry
    return None


def upsert_name_wrap_role(
    roles_path: PathLike,
    note: str,
    *,
    width: int | None = None,
    max_lines: int | None = None,
    font: int | None = None,
    min_font: int | None = None,
) -> Path:
    """Create/update a ``nameWraps`` rule for *note* in ``wolfdawn-roles.json``.

    WolfDawn reads this file from the same directory as ``names.json``.
    """
    path = Path(roles_path)
    data = load_name_wrap_roles(path)
    wraps = data.get("nameWraps")
    if not isinstance(wraps, list):
        wraps = []
        data["nameWraps"] = wraps

    entry = None
    for item in wraps:
        if isinstance(item, dict) and str(item.get("note") or "") == note:
            entry = item
            break
    if entry is None:
        entry = {"note": note}
        wraps.append(entry)

    if width is not None and int(width) > 0:
        entry["width"] = int(width)
    if max_lines is not None and int(max_lines) > 0:
        entry["maxLines"] = int(max_lines)
    if font is not None and int(font) > 0:
        entry["font"] = int(font)
    if min_font is not None and int(min_font) > 0:
        entry["minFont"] = int(min_font)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
