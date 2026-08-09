"""Parsing helpers for compact numeric ID selections."""

from __future__ import annotations

import re
from functools import lru_cache


_RANGE_PART = re.compile(r"^(\d+)\s*(?:[-\u2013\u2014]\s*(\d+))?$")


@lru_cache(maxsize=128)
def parse_id_ranges(value: str, maximum: int = 99999) -> tuple[tuple[int, int], ...]:
    """Return sorted, merged inclusive intervals from a compact ID string.

    ``value`` accepts comma-separated IDs and ranges such as
    ``"35, 37-40, 402"``. Hyphens, en dashes, and em dashes are accepted.
    """
    if not isinstance(value, str):
        raise ValueError("ID ranges must be text")

    text = value.strip()
    if not text:
        raise ValueError("Enter at least one variable ID")

    intervals: list[tuple[int, int]] = []
    for raw_part in text.split(","):
        part = raw_part.strip()
        match = _RANGE_PART.fullmatch(part)
        if match is None:
            raise ValueError(f"Invalid ID or range: {part or '(empty entry)'}")

        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start > maximum or end > maximum:
            raise ValueError(f"Variable IDs must be between 0 and {maximum}")
        if end < start:
            raise ValueError(f"Range end must not be less than its start: {part}")
        intervals.append((start, end))

    intervals.sort()
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1] + 1:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def normalize_id_ranges(value: str, maximum: int = 99999) -> str:
    """Validate and return a canonical compact range string."""
    return ", ".join(
        str(start) if start == end else f"{start}-{end}"
        for start, end in parse_id_ranges(value, maximum)
    )


def id_in_ranges(identifier: int, value: str, maximum: int = 99999) -> bool:
    """Return whether ``identifier`` belongs to one of ``value``'s intervals."""
    return any(start <= identifier <= end for start, end in parse_id_ranges(value, maximum))


def legacy_exclusive_range(minimum: int, maximum: int) -> str:
    """Convert the former ``range(minimum, maximum)`` config to display text."""
    if maximum <= minimum:
        return str(minimum)
    inclusive_maximum = maximum - 1
    return (
        str(minimum)
        if minimum == inclusive_maximum
        else f"{minimum}-{inclusive_maximum}"
    )
