"""Shared [Speaker]: prefix parsing for dialogue lines.

Handles RPG Maker control codes inside speaker brackets, e.g.
``[\\C[10]Hp Drink\\C[0]]: dialogue`` where inner ``[10]`` must not end the match early.
"""

from __future__ import annotations

import re

# Inner text of [Speaker] — allows \C[n], \c[n], \i[n], \n[actorId], etc.
# The control-code branch (\X[...]) keeps the inner [..] from ending the bracket early.
SPEAKER_BRACKET_INNER = r"(?:\\[A-Za-z]+\[[^\]]*\]|[^\]\n])+"

# A bare [Speaker]: / [Speaker]| / [Speaker]： prefix.
_PREFIX_PATTERN = rf"^\[{SPEAKER_BRACKET_INNER}\]\s*[|:：]\s*"
SPEAKER_PREFIX_RE = re.compile(_PREFIX_PATTERN, re.IGNORECASE)

SPEAKER_TAG_RE = re.compile(
    rf"^\[({SPEAKER_BRACKET_INNER})\]",
    re.IGNORECASE,
)

# Dialogue body after an optional [Speaker]: prefix (text.py lineTextRegex, etc.)
SPEAKER_PREFIX_OPTIONAL_RE = re.compile(
    rf"(?:{_PREFIX_PATTERN})?(.+)",
    re.IGNORECASE,
)


def strip_speaker_prefix(text: str) -> str:
    """Remove a leading ``[Speaker]:`` / ``[Speaker]|`` / ``[Speaker]：`` prefix."""
    if not text:
        return text
    return SPEAKER_PREFIX_RE.sub("", text, count=1)


def extract_dialogue_after_speaker(text: str) -> str | None:
    """Return dialogue body after an optional ``[Speaker]:`` prefix, or ``None``."""
    if not text:
        return None
    m = SPEAKER_PREFIX_OPTIONAL_RE.match(text)
    return m.group(1) if m else None
