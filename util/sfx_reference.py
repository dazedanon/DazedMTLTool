"""Local, dynamically matched Japanese SFX reference context.

The bundled J-Ono snapshot is a semantic reference, not an authoritative
replacement table. Only records matched in the current source payload are
formatted for the model; the full dictionary is never sent to an API.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata

from util.paths import SFX_REFERENCE_PATH


MAX_MATCHED_ENTRIES = 12
MAX_DISPLAY_VARIANTS = 8
MAX_SENSES_PER_ENTRY = 6
MAX_EQUIVALENTS_PER_SENSE = 8

_TYPE_LABELS = {
    "o": "sound",
    "v": "voice or vocal sound",
    "s": "state or condition",
    "m": "motion or movement",
    "e": "emotion or feeling",
    "c": "visual or meta cue",
    "": "",
}
_HIRAGANA_RE = re.compile(r"^[ぁ-ゔー]+$")
_KATAKANA_RE = re.compile(r"^[ァ-ヴー]+$")
_FENCED_JSON_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value))


def _kana_count(value: str) -> int:
    return sum(
        1 for char in value
        if "ぁ" <= char <= "ゔ" or "ァ" <= char <= "ヴ"
    )


def _same_script(char: str, script: str) -> bool:
    if script == "hiragana":
        return "ぁ" <= char <= "ゔ" or char == "ー"
    return "ァ" <= char <= "ヴ" or char == "ー"


def _is_japanese_text_char(char: str) -> bool:
    return (
        "ぁ" <= char <= "ゔ"
        or "ァ" <= char <= "ヴ"
        or "一" <= char <= "龠"
        or char in "ー々〆〤"
    )


def _has_safe_boundaries(text: str, start: int, end: int, variant: str) -> bool:
    """Reject a kana term embedded inside a longer run of the same script."""
    if _HIRAGANA_RE.fullmatch(variant):
        # Hiragana spellings frequently collide with ordinary grammar and
        # verbs (for example the J-Ono SFX する versus the verb "to do").
        # Only accept them as isolated/stylized tokens. Katakana remains the
        # reliable inline signal and can attach to surrounding hiragana.
        if start > 0 and _is_japanese_text_char(text[start - 1]):
            return False
        if end < len(text) and _is_japanese_text_char(text[end]):
            return False
        return True
    elif _KATAKANA_RE.fullmatch(variant):
        script = "katakana"
    else:
        return True
    if start > 0 and _same_script(text[start - 1], script):
        return False
    if end < len(text) and _same_script(text[end], script):
        return False
    return True


def _collect_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_collect_strings(item))
        return result
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_collect_strings(item))
        return result
    return []


def source_strings(payload) -> list[str]:
    """Extract only translatable string values from a JSON or plain payload."""
    if not isinstance(payload, str):
        return _collect_strings(payload)
    stripped = payload.strip()
    if stripped.startswith("```"):
        stripped = _FENCED_JSON_RE.sub("", stripped)
    try:
        parsed = json.loads(stripped)
    except (TypeError, json.JSONDecodeError):
        return [payload]
    values = _collect_strings(parsed)
    return values or [payload]


@dataclass(frozen=True)
class SfxMatch:
    entry: dict
    matched_variant: str


class SfxReference:
    """Validated snapshot and deterministic longest-match index."""

    def __init__(self, document: dict):
        if document.get("schema_version") != 1:
            raise ValueError("Unsupported SFX reference schema")
        source = document.get("source")
        entries = document.get("entries")
        if not isinstance(source, dict) or not isinstance(entries, list):
            raise ValueError("Malformed SFX reference document")
        self.source = dict(source)
        self.entries = tuple(entries)
        self._by_initial: dict[str, list[tuple[str, int, dict]]] = {}
        seen_ids: set[str] = set()
        for order, entry in enumerate(self.entries):
            entry_id = str(entry.get("id") or "").strip()
            variants = entry.get("variants")
            senses = entry.get("senses")
            if (
                not entry_id or entry_id in seen_ids
                or not isinstance(variants, list) or not variants
                or not isinstance(senses, list) or not senses
            ):
                raise ValueError(f"Malformed SFX reference entry: {entry_id!r}")
            seen_ids.add(entry_id)
            normalized_seen: set[str] = set()
            for raw_variant in variants:
                variant = _normalize(str(raw_variant).strip())
                # One-kana interjections such as あ and ん collide with ordinary
                # dialogue far too often to be safe automatic context.
                if not variant or _kana_count(variant) <= 1 or variant in normalized_seen:
                    continue
                normalized_seen.add(variant)
                self._by_initial.setdefault(variant[0], []).append(
                    (variant, order, entry)
                )
        for candidates in self._by_initial.values():
            candidates.sort(key=lambda item: (-len(item[0]), item[1], item[0]))

    @property
    def identity(self) -> dict:
        return dict(self.source)

    def match(self, payload, limit: int = MAX_MATCHED_ENTRIES) -> list[SfxMatch]:
        if limit <= 0:
            return []
        selected: list[SfxMatch] = []
        selected_ids: set[str] = set()
        for raw_text in source_strings(payload):
            text = _normalize(raw_text)
            occupied: list[tuple[int, int]] = []
            position = 0
            while position < len(text):
                candidates = self._by_initial.get(text[position], ())
                accepted = None
                for variant, _order, entry in candidates:
                    end = position + len(variant)
                    if not text.startswith(variant, position):
                        continue
                    if not _has_safe_boundaries(text, position, end, variant):
                        continue
                    if any(position < used_end and end > used_start for used_start, used_end in occupied):
                        continue
                    accepted = (variant, end, entry)
                    break
                if accepted is None:
                    position += 1
                    continue
                variant, end, entry = accepted
                occupied.append((position, end))
                entry_id = str(entry["id"])
                if entry_id not in selected_ids:
                    selected.append(SfxMatch(entry=entry, matched_variant=variant))
                    selected_ids.add(entry_id)
                    if len(selected) >= limit:
                        return selected
                position = end
        return selected


@lru_cache(maxsize=4)
def _load_cached(path_text: str) -> SfxReference:
    path = Path(path_text)
    document = json.loads(path.read_text(encoding="utf-8"))
    return SfxReference(document)


def load_sfx_reference(path: str | Path | None = None) -> SfxReference:
    resolved = Path(path or SFX_REFERENCE_PATH).resolve()
    return _load_cached(str(resolved))


def clear_sfx_reference_cache() -> None:
    _load_cached.cache_clear()


def sfx_reference_identity(path: str | Path | None = None) -> dict:
    try:
        return load_sfx_reference(path).identity
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def build_sfx_reference_text(
    payload,
    *,
    enabled: bool = True,
    path: str | Path | None = None,
    limit: int = MAX_MATCHED_ENTRIES,
) -> str:
    """Return a compact, explicitly non-authoritative block for this payload."""
    if not enabled:
        return ""
    try:
        matches = load_sfx_reference(path).match(payload, limit=limit)
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    if not matches:
        return ""

    lines = [
        "Japanese SFX reference (contextual suggestions, not approved fixed translations).",
        "Choose the sense that fits the scene and render it naturally in the requested target language.",
        "The English equivalents below are semantic hints, not required output wording.",
        "",
    ]
    for match in matches:
        entry = match.entry
        variants = [match.matched_variant]
        for raw_variant in entry.get("variants", []):
            variant = _normalize(raw_variant)
            if variant not in variants:
                variants.append(variant)
        lines.append(f"- {' / '.join(variants[:MAX_DISPLAY_VARIANTS])}")
        for sense in entry.get("senses", [])[:MAX_SENSES_PER_ENTRY]:
            equivalents = [
                str(item).strip() for item in sense.get("equivalents", [])
                if str(item).strip()
            ][:MAX_EQUIVALENTS_PER_SENSE]
            meanings = [
                str(item).strip() for item in sense.get("meanings", [])
                if str(item).strip()
            ]
            details = []
            if equivalents:
                details.append("equivalents: " + ", ".join(equivalents))
            if meanings:
                details.append("meaning: " + "; ".join(meanings))
            type_label = _TYPE_LABELS.get(str(sense.get("type") or ""), "")
            if type_label:
                details.append("kind: " + type_label)
            if details:
                lines.append("  - " + "; ".join(details))
        lines.append("")
    return "\n" + "\n".join(lines).rstrip() + "\n"
