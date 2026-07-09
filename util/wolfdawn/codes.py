"""WOLF RPG Editor inline control-code helpers for WolfDawn JSON.

WolfDawn ``strings-inject`` requires each ``text`` line to carry the same
backslash control codes as its ``source`` (only the human-readable words may
change). Models often break codes (e.g. ``\\^`` becomes ``\\ ^``). These
helpers protect codes during translation and repair them before inject.

Font sizes (``\\f[N]``) are an exception: Fix-wrap Manual mode and
``names-wrap`` intentionally shrink them. Repair keeps those sizes from
``text`` while restoring every other code from ``source``.
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

# Wolf font-size codes: ``\f[18]``, ``\f[20]``, etc.
WOLF_FONT_SIZE_RE = re.compile(r"\\f\[(\d+)\]")


def detect_font_sizes(text: str) -> list[int]:
    """Return sorted unique ``\\f[N]`` sizes in *text*."""
    if not isinstance(text, str) or not text:
        return []
    sizes: set[int] = set()
    for match in WOLF_FONT_SIZE_RE.finditer(text):
        try:
            sizes.add(int(match.group(1)))
        except (TypeError, ValueError):
            continue
    return sorted(sizes)


def infer_base_font_size(text: str, *, default: int = 18) -> int:
    """Guess the body / \"normal\" ``\\f[N]`` size for *text*.

    Emphasis overrides (e.g. ``\\f[20]…\\f[18]``) keep a larger size for a span
    then restore the body size. Prefer the most common size; on a tie, the
    smaller one (body over emphasis).
    """
    if not isinstance(text, str) or not text:
        return int(default)
    counts: dict[int, int] = {}
    for match in WOLF_FONT_SIZE_RE.finditer(text):
        try:
            size = int(match.group(1))
        except (TypeError, ValueError):
            continue
        counts[size] = counts.get(size, 0) + 1
    if not counts:
        return int(default)
    top = max(counts.values())
    return min(size for size, n in counts.items() if n == top)


def ensure_leading_font_size(text: str, size: int) -> str:
    """Ensure *text* begins with ``\\f[size]`` so Wolf sets line height from the start.

    Mid-line ``\\f[N]`` alone (e.g. ``"That \\c[21]\\f[14]cafe…``) leaves the
    opening glyphs on the default face and mis-aligns the row. WolfDawn
    ``names-wrap`` always leads with the body size for the same reason.
    """
    if not isinstance(text, str) or not text or int(size) <= 0:
        return text
    size = int(size)
    lead = rf"\f[{size}]"
    # Already starts with the desired body size.
    m = WOLF_FONT_SIZE_RE.match(text)
    if m and int(m.group(1)) == size:
        return text
    # Replace a different leading \\f[N] with the body size.
    if m:
        return lead + text[m.end() :]
    return lead + text


def scale_font_sizes(
    text: str,
    new_base: int,
    *,
    old_base: int | None = None,
    min_size: int = 8,
) -> tuple[str, int]:
    """Scale every ``\\f[N]`` proportionally when the body font changes.

    Example: body ``\\f[18]`` with emphasis ``\\f[20]`` shrunk to body 14 becomes
    ``\\f[16]`` / ``\\f[14]`` (``round(N * new_base / old_base)``, floored at
    *min_size*). Always ensures a leading ``\\f[new_base]`` so Wolf measures the
    line from the body size (fixes mid-line emphasis like
    ``"That \\c[21]\\f[14]cafe\\c[19]\\f[13]…``).

    When *text* has no ``\\f[N]``, prepends ``\\f[new_base]``.
    Returns ``(new_text, replacements)``.
    """
    if not isinstance(text, str) or not text.strip() or int(new_base) <= 0:
        return text, 0
    new_base = int(new_base)
    min_size = max(1, int(min_size))
    matches = list(WOLF_FONT_SIZE_RE.finditer(text))
    if not matches:
        return ensure_leading_font_size(text, new_base), 1

    base = int(old_base) if old_base is not None and int(old_base) > 0 else infer_base_font_size(text)
    if base <= 0:
        base = new_base

    def _scale(match: re.Match) -> str:
        try:
            old = int(match.group(1))
        except (TypeError, ValueError):
            return match.group(0)
        scaled = max(min_size, int(round(old * new_base / base)))
        return rf"\f[{scaled}]"

    had_leading = bool(WOLF_FONT_SIZE_RE.match(text))
    new_text = WOLF_FONT_SIZE_RE.sub(_scale, text)
    new_text = ensure_leading_font_size(new_text, new_base)
    count = len(matches) + (0 if had_leading else 1)
    return new_text, count


def _control_code_tokens(text: str) -> list[str]:
    """Return the sequence of WolfDawn-compared control codes in *text*."""
    if not isinstance(text, str) or not text:
        return []
    return [m.group(0) for m in WOLF_INLINE_CODE_RE.finditer(text)]


def _normalize_font_size_codes(text: str) -> str:
    """Replace every ``\\f[N]`` with a placeholder so size values are ignored."""
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    return WOLF_FONT_SIZE_RE.sub(r"\\f[_]", text)


def font_size_codes_differ(source: str, text: str) -> bool:
    """True when *source* and *text* differ only in ``\\f[N]`` size values / count.

    Used after ``wolf names-wrap`` shrinks overflow with a leading ``\\f[N]`` and
    scales inline font codes. Other control-code drift (missing ``\\c``, etc.)
    returns False so inject still requires an explicit allow-code-drift.
    """
    if not isinstance(source, str) or not isinstance(text, str):
        return False
    if source == text:
        return False
    src_codes = _control_code_tokens(source)
    txt_codes = _control_code_tokens(text)
    if src_codes == txt_codes:
        return False
    # Same non-font codes, but font sizes / leading shrink differ.
    src_norm = _normalize_font_size_codes(source)
    txt_norm = _normalize_font_size_codes(text)
    if _control_code_tokens(src_norm) == _control_code_tokens(txt_norm):
        return True
    # Leading shrink adds an extra \\f that source never had.
    src_f = WOLF_FONT_SIZE_RE.findall(source)
    txt_f = WOLF_FONT_SIZE_RE.findall(text)
    if not txt_f:
        return False
    src_non_f = [c for c in src_codes if not WOLF_FONT_SIZE_RE.fullmatch(c)]
    txt_non_f = [c for c in txt_codes if not WOLF_FONT_SIZE_RE.fullmatch(c)]
    return src_non_f == txt_non_f and (src_f != txt_f or len(txt_f) > len(src_f))


def names_doc_has_font_size_drift(doc: dict[str, Any]) -> bool:
    """True when any names.json entry has font-size-only control-code drift."""
    if not isinstance(doc, dict) or doc.get("kind") != "names":
        return False
    for entry in doc.get("names") or []:
        if not isinstance(entry, dict):
            continue
        src, txt = entry.get("source"), entry.get("text")
        if isinstance(src, str) and isinstance(txt, str) and font_size_codes_differ(src, txt):
            return True
    return False


def document_has_font_size_drift(doc: dict[str, Any]) -> bool:
    """True when any leaf in a WolfDawn document has font-size-only ``\\f`` drift.

    Covers ``names``, ``db``, maps/events, and other extract kinds so inject can
    auto-pass ``--allow-code-drift`` after Fix-wrap Manual font shrink.
    """
    if not isinstance(doc, dict):
        return False
    if doc.get("kind") == "names":
        return names_doc_has_font_size_drift(doc)
    for entry in _walk_entries(doc):
        if not isinstance(entry, dict):
            continue
        src, txt = entry.get("source"), entry.get("text")
        if isinstance(src, str) and isinstance(txt, str) and font_size_codes_differ(src, txt):
            return True
    return False


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

    ``\\f[N]`` sizes are taken from *text* when present (manual wrap / names-wrap
    shrink). Other control codes (``\\c``, ``\\^``, …) always come from *source*.
    A leading body ``\\f[N]`` that *source* lacks is kept from *text*.

    When *source* has no inline codes at all (typical spoken ``Name\\nbody``),
    *text* is returned unchanged so a body ``\\f[N]`` after the nameplate cannot
    be mis-read as a code slot and wipe the dialogue.
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
    txt_font_sizes = _font_sizes_in_order(txt_rest)

    if not src_parts:
        return out_prefix + txt_rest

    # Source has no inline codes to restore. Keep the translation intact -
    # including Manual-wrap ``Name\\n\\f[N]body`` (body font after the nameplate).
    # Slot-rebuilding would treat the mid-line ``\\f`` as a break, keep only
    # ``Name\\n``, prepend ``\\f[N]``, and drop the body (``\\f[N]Name\\n``).
    if not any(kind == "code" for kind, _ in src_parts):
        return out_prefix + txt_rest

    # Rebuild using source code skeleton + translated literal slots.
    # Font sizes prefer the translation (intentional shrink / body \\f).
    rebuilt: list[str] = []
    lit_i = 0
    font_i = 0

    src_starts_with_f = bool(
        src_parts
        and src_parts[0][0] == "code"
        and WOLF_FONT_SIZE_RE.fullmatch(src_parts[0][1])
    )
    if txt_font_sizes and not src_starts_with_f:
        # Manual wrap / names-wrap often prepend a body \\f[N] source never had.
        rebuilt.append(rf"\f[{txt_font_sizes[0]}]")
        font_i = 1

    for kind, val in src_parts:
        if kind == "code":
            if WOLF_FONT_SIZE_RE.fullmatch(val) and font_i < len(txt_font_sizes):
                rebuilt.append(rf"\f[{txt_font_sizes[font_i]}]")
                font_i += 1
            else:
                rebuilt.append(val)
        else:
            if lit_i < len(txt_lit):
                # Last source literal: keep every remaining translated literal so
                # extra mid-line ``\\f[N]`` in *text* cannot truncate the body.
                if lit_i == len(src_lit) - 1 and len(txt_lit) > lit_i + 1:
                    rebuilt.append("".join(txt_lit[lit_i:]))
                    lit_i = len(txt_lit)
                else:
                    rebuilt.append(txt_lit[lit_i])
                    lit_i += 1
            else:
                rebuilt.append(val)
    return out_prefix + "".join(rebuilt)


def _font_sizes_in_order(text: str) -> list[int]:
    """Return every ``\\f[N]`` size in *text* in left-to-right order."""
    if not isinstance(text, str) or not text:
        return []
    out: list[int] = []
    for match in WOLF_FONT_SIZE_RE.finditer(text):
        try:
            out.append(int(match.group(1)))
        except (TypeError, ValueError):
            continue
    return out


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
