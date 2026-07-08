"""Selective word-wrap for WolfDawn translated JSON.

Bulk ``wolf relayout`` / ``desc-relayout`` cannot target individual DB rows or
custom field types (e.g. ``セリフ_メッセージ``, ``好きなもの_コメント``).
This module wraps ``text`` fields in ``translated/*.project.json`` for checked
database sheets and field patterns, then the user re-injects only those files.

``wolf relayout`` for maps already skips messages that fit; use it for dialogue
overflow. Use selective JSON wrap for custom DB columns and fine-grained control.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import util.dazedwrap as dazedwrap
from util.wolfdawn.db_classify import group_key, json_file_from_doc

# Field-name presets for the Relayout tab (match ``fieldName`` substrings).
FIELD_PRESET_DESCRIPTIONS = re.compile(r"説明|Description", re.IGNORECASE)
FIELD_PRESET_COMMENTS = re.compile(r"コメント")
FIELD_PRESET_DIALOGUE = re.compile(r"セリフ|台詞|会話")
FIELD_PRESET_MESSAGES = re.compile(r"メッセージ")
FIELD_PRESET_ALL = re.compile(r".", re.DOTALL)

FIELD_PRESETS: dict[str, re.Pattern[str]] = {
    "descriptions": FIELD_PRESET_DESCRIPTIONS,
    "comments": FIELD_PRESET_COMMENTS,
    "dialogue": FIELD_PRESET_DIALOGUE,
    "messages": FIELD_PRESET_MESSAGES,
}


@dataclass
class WrapResult:
    files_touched: int = 0
    lines_wrapped: int = 0
    lines_skipped: int = 0
    touched_json: list[str] | None = None

    def __post_init__(self):
        if self.touched_json is None:
            self.touched_json = []


def combine_field_patterns(enabled: frozenset[str]) -> re.Pattern[str] | None:
    """Merge enabled preset keys into one regex, or None when nothing selected."""
    if not enabled:
        return None
    parts = []
    for key in enabled:
        pat = FIELD_PRESETS.get(key)
        if pat is not None and key != "all":
            parts.append(f"(?:{pat.pattern})")
    if "all" in enabled:
        return FIELD_PRESET_ALL
    if not parts:
        return None
    return re.compile("|".join(parts), re.IGNORECASE)


def _visible_length(text: str) -> int:
    return dazedwrap._get_visible_length(text)


def line_needs_wrap(text: str, width: int, *, min_visible: int = 0) -> bool:
    """True when *text* is long enough and exceeds *width* on at least one line."""
    if not isinstance(text, str) or not text.strip() or width <= 0:
        return False
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines:
        visible = _visible_length(text)
        if min_visible > 0 and visible < min_visible:
            return False
        return visible > width
    total_visible = max((_visible_length(line) for line in lines), default=0)
    if min_visible > 0 and total_visible < min_visible:
        return False
    return any(_visible_length(line) > width for line in lines)


def wrap_line_text(text: str, width: int) -> str:
    """Word-wrap one ``text`` value, preserving WOLF inline codes.

    Width is measured with :func:`util.dazedwrap._get_visible_length`, so
    ``\\c[N]``, ``\\f[N]``, and similar codes do not consume box width.
    """
    if not isinstance(text, str) or not text.strip() or width <= 0:
        return text
    return dazedwrap.wrapText(text, width)


def group_type_indices(doc: dict[str, Any], group_keys: frozenset[str]) -> list[int]:
    """Return sorted DB ``type`` indices for selected sheet keys."""
    jf = json_file_from_doc(doc)
    indices: set[int] = set()
    for group in doc.get("groups") or []:
        type_name = str(group.get("typeName") or "")
        if group_key(jf, type_name) not in group_keys:
            continue
        try:
            idx = int(group.get("type", -1))
        except (TypeError, ValueError):
            continue
        if idx >= 0:
            indices.add(idx)
    return sorted(indices)


def wrap_db_document(
    doc: dict[str, Any],
    *,
    group_keys: frozenset[str],
    field_pattern: re.Pattern[str] | None,
    width: int,
    min_visible: int = 0,
    only_if_overflow: bool = True,
) -> tuple[int, int]:
    """Wrap matching lines in one ``kind: db`` document. Returns (wrapped, skipped)."""
    if doc.get("kind") != "db" or not group_keys:
        return 0, 0
    jf = json_file_from_doc(doc)
    wrapped = skipped = 0
    for group in doc.get("groups") or []:
        type_name = str(group.get("typeName") or "")
        if group_key(jf, type_name) not in group_keys:
            continue
        for line in group.get("lines") or []:
            field_name = str(line.get("fieldName") or "")
            if field_pattern is not None and not field_pattern.search(field_name):
                skipped += 1
                continue
            text = line.get("text")
            if not isinstance(text, str) or not text.strip():
                skipped += 1
                continue
            if only_if_overflow and not line_needs_wrap(
                text, width, min_visible=min_visible
            ):
                skipped += 1
                continue
            new_text = wrap_line_text(text, width)
            if new_text != text:
                line["text"] = new_text
                wrapped += 1
            else:
                skipped += 1
    return wrapped, skipped


def wrap_db_translated_dir(
    translated_dir: str | Path,
    *,
    group_keys: frozenset[str],
    field_presets: frozenset[str],
    width: int,
    min_visible: int = 0,
    only_if_overflow: bool = True,
) -> WrapResult:
    """Apply selective wrap to all ``*.project.json`` under ``translated/``."""
    base = Path(translated_dir)
    result = WrapResult()
    if not base.is_dir() or not group_keys:
        return result
    field_pattern = combine_field_patterns(field_presets)
    if field_pattern is None:
        return result

    for path in sorted(base.glob("*.project.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if doc.get("kind") != "db":
            continue
        w, s = wrap_db_document(
            doc,
            group_keys=group_keys,
            field_pattern=field_pattern,
            width=width,
            min_visible=min_visible,
            only_if_overflow=only_if_overflow,
        )
        if w:
            path.write_text(
                json.dumps(doc, ensure_ascii=False, indent=4) + "\n",
                encoding="utf-8",
            )
            result.files_touched += 1
            result.lines_wrapped += w
            result.touched_json.append(path.name)
        result.lines_skipped += s
    return result


def collect_field_names(translated_dir: str | Path) -> list[str]:
    """Sorted unique ``fieldName`` values from staged/translated DB JSON."""
    base = Path(translated_dir)
    names: set[str] = set()
    if not base.is_dir():
        return []
    for path in base.glob("*.project.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if doc.get("kind") != "db":
            continue
        for group in doc.get("groups") or []:
            for line in group.get("lines") or []:
                fn = str(line.get("fieldName") or "").strip()
                if fn:
                    names.add(fn)
    return sorted(names)
