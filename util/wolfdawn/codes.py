"""WOLF RPG Editor inline control-code helpers for WolfDawn JSON.

WolfDawn ``strings-inject`` requires each ``text`` line to carry the same
backslash control codes as its ``source`` (only the human-readable words may
change). Models often break codes (e.g. ``\\^`` becomes ``\\ ^``). These
helpers protect codes during translation and repair them before inject.
"""

from __future__ import annotations

import re
from typing import Any

from util import speakers as wolf_speakers

# Inline codes WolfDawn compares during inject (see strings-inject guard output).
# Order matters: longer bracketed forms before single-letter fallbacks.
WOLF_INLINE_CODE_RE = re.compile(
    r"\\(?:"
    r"r\[[^\]]*\]|"  # ruby \r[kanji,kana]
    r"c(?:self)?\[[^\]]*\]|"  # \c[...] / \cself[...]
    r"[A-Za-z]+\[[^\]]*\]|"  # \font[0], \cdb[21:78:0], \wE[1], ...
    r"\^|"  # \^ (wait / beat — often mangled to "\ ^")
    r"[ @<>\-]|"  # other single-char escapes Wolf uses
    r"[A-Za-z]"  # \n, \c, \f, ...
    r")"
)

# Placeholder transport (same convention as util.translation.protect_script_codes).
_PLACEHOLDER_PREFIX = "__WOLF_CODE_"


def _tokenize(rest: str) -> list[tuple[str, str]]:
    """Split *rest* into ``('lit', ...)`` and ``('code', ...)`` tokens."""
    if not rest:
        return []
    out: list[tuple[str, str]] = []
    last = 0
    for m in WOLF_INLINE_CODE_RE.finditer(rest):
        if m.start() > last:
            out.append(("lit", rest[last : m.start()]))
        out.append(("code", m.group(0)))
        last = m.end()
    if last < len(rest):
        out.append(("lit", rest[last:]))
    return out


def _fix_spurious_spaces_in_codes(source: str, text: str) -> str:
    """Undo common model errors like ``\\ ^`` when *source* has ``\\^``."""
    for m in WOLF_INLINE_CODE_RE.finditer(source):
        code = m.group(0)
        # Single-char escapes: \^ \c etc. Models often insert a space after \\.
        if len(code) == 2 and code[1] not in (" ", "\t"):
            spaced = f"{code[0]} {code[1]}"
            if spaced in text:
                text = text.replace(spaced, code, 1)
    return text


def rebuild_text_preserving_source_codes(source: str, text: str) -> str:
    """Return *text* with *source*'s inline code tokens and translated literals.

  Keeps any leading ``@<option>\\n`` window prefix from the translated line when
  present; otherwise preserves the source prefix byte-for-byte.
    """
    if not isinstance(source, str) or not isinstance(text, str):
        return text
    if source == text:
        return text

    src_prefix, src_rest = wolf_speakers.split_window_prefix(source)
    txt_prefix, txt_rest = wolf_speakers.split_window_prefix(text)
    out_prefix = txt_prefix if txt_prefix else src_prefix

    txt_rest = _fix_spurious_spaces_in_codes(src_rest, txt_rest)

    src_parts = _tokenize(src_rest)
    txt_parts = _tokenize(txt_rest)
    src_lit = [p[1] for p in src_parts if p[0] == "lit"]
    txt_lit = [p[1] for p in txt_parts if p[0] == "lit"]

    if not src_parts:
        return out_prefix + txt_rest

    # Rebuild using source code skeleton + translated literal slots.
    rebuilt: list[str] = []
    lit_i = 0
    for kind, val in src_parts:
        if kind == "code":
            rebuilt.append(val)
        else:
            if lit_i < len(txt_lit):
                rebuilt.append(txt_lit[lit_i])
                lit_i += 1
            else:
                rebuilt.append(val)
    return out_prefix + "".join(rebuilt)


def protect_wolf_codes(text: str) -> tuple[str, dict[str, str]]:
    """Replace inline WOLF codes with placeholders before sending text to the model."""
    if not text or not isinstance(text, str):
        return text, {}
    replacements: dict[str, str] = {}
    counter = 0

    def _sub(m: re.Match) -> str:
        nonlocal counter
        key = f"{_PLACEHOLDER_PREFIX}{counter}__"
        replacements[key] = m.group(0)
        counter += 1
        return key

    protected = WOLF_INLINE_CODE_RE.sub(_sub, text)
    return protected, replacements


def restore_wolf_code_placeholders(text: str, replacements: dict[str, str]) -> str:
    if not text or not replacements:
        return text
    out = text
    for key, original in replacements.items():
        out = out.replace(key, original)
    return out


def repair_entry(entry: dict[str, Any]) -> tuple[bool, str]:
    """Repair one ``{source, text}`` leaf. Returns (changed, reason)."""
    src, txt = entry.get("source"), entry.get("text")
    if not isinstance(src, str) or not isinstance(txt, str) or not src or src == txt:
        return False, ""
    fixed = rebuild_text_preserving_source_codes(src, txt)
    if fixed == txt:
        return False, ""
    entry["text"] = fixed
    return True, "codes"


def _walk_entries(data: dict) -> list[dict]:
    kind = data.get("kind")
    entries: list[dict] = []
    if kind in ("map", "common"):
        for scene in data.get("scenes") or []:
            entries.extend(scene.get("lines") or [])
    elif kind == "db":
        for group in data.get("groups") or []:
            entries.extend(group.get("lines") or [])
    elif kind in ("gamedat", "txt"):
        entries.extend(data.get("lines") or [])
    elif kind == "txt-dir":
        for file_doc in data.get("files") or []:
            entries.extend(file_doc.get("lines") or [])
    return entries


def repair_document(data: dict) -> tuple[dict, list[str]]:
    """Repair every ``{source, text}`` leaf in a WolfDawn document in place."""
    notes: list[str] = []
    for entry in _walk_entries(data):
        changed, _reason = repair_entry(entry)
        if changed:
            row = entry.get("rowName") or entry.get("speaker") or ""
            notes.append(
                f"event {entry.get('event', entry.get('row', '?'))} "
                f"cmd {entry.get('cmd', entry.get('field', '?'))} "
                f"str {entry.get('str', '')} {row}".strip()
            )
    return data, notes
