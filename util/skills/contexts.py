"""Load per-call translation instruction templates from data/translation_contexts.json."""

from __future__ import annotations

import json
import os
from typing import Any

from util.paths import TRANSLATION_CONTEXTS_PATH

_cache: dict[str, Any] | None = None
_cache_mtime: float | None = None


def _load() -> dict[str, Any]:
    global _cache, _cache_mtime
    path = TRANSLATION_CONTEXTS_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Translation contexts file missing: {path}")
    mtime = path.stat().st_mtime
    if _cache is not None and _cache_mtime == mtime:
        return _cache
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"translation_contexts.json must be an object: {path}")
    _cache = data
    _cache_mtime = mtime
    return data


def ctx(path: str, *, language: str | None = None, **kwargs: Any) -> str:
    """Return a formatted history string for ``section.key``.

    ``{language}`` defaults to the ``language`` env / argument (capitalized).
    Extra kwargs fill other ``{placeholders}`` (e.g. ``context``).
    """
    if not path or "." not in path:
        raise KeyError(f"Context path must be 'section.key', got {path!r}")
    section_name, key = path.split(".", 1)
    data = _load()
    section = data.get(section_name)
    if not isinstance(section, dict):
        raise KeyError(f"Unknown translation context section: {section_name!r}")
    template = section.get(key)
    if not isinstance(template, str) or not template.strip():
        raise KeyError(f"Unknown translation context key: {path!r}")

    lang = language or os.getenv("language", "English")
    lang = str(lang).capitalize()
    values = {"language": lang, **kwargs}
    try:
        return template.format(**values)
    except KeyError as exc:
        raise KeyError(
            f"Missing placeholder {exc.args[0]!r} for context {path!r}"
        ) from exc


def reload_contexts() -> None:
    """Clear the in-memory cache so the next ctx() re-reads from disk."""
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None
